# scripts/add-breeding-farm-to-horse-template.py
#
# Requires the installed Horse Templates feature.
#
# Adds Breeding Farm to:
#   - Template creation and editing
#   - Existing/new-name registration
#   - Template persistence
#   - Automatic Race Checklist defaults
#   - Apply horse template
#
# Preserves the existing breeding-farm widget key.
# Existing templates receive a nullable breeding_farm_id column
# automatically on first feature use.
#
# Does not infer farms for existing templates.
# Does not rewrite historical checklists.
# Does not change menu permissions or pagination.
#
# Stop Streamlit before running:
#
# python scripts/add-breeding-farm-to-horse-template.py app.py

NEW_SAVE = r'''
def _ht_save(values, template_id=None):
    from contextlib import closing

    owner = _ht_owner()

    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _ht_schema(conn)

        if template_id is not None:
            existing = conn.execute(
                "SELECT 1 FROM horse_profile_templates "
                "WHERE id=? AND owner_id=?",
                (template_id, owner),
            ).fetchone()

            if existing is None:
                raise ValueError(
                    "This horse template is no longer available."
                )

        fields = list(_HT_FIELDS)

        ids = {
            field: _ht_reference(
                conn,
                owner,
                field,
                values.get(field),
            )
            for field in fields
        }

        duplicate = conn.execute(
            "SELECT id FROM horse_profile_templates "
            "WHERE owner_id=? AND horse_id=?",
            (owner, ids["horse"]),
        ).fetchone()

        if duplicate and duplicate["id"] != template_id:
            raise ValueError(
                "This horse already has a template. "
                "Select that template to edit it."
            )

        columns = [
            field + "_id"
            for field in fields
        ]

        args = tuple(
            ids[field]
            for field in fields
        )

        if template_id is None:
            placeholders = ", ".join(
                "?"
                for _ in range(len(columns) + 1)
            )

            return conn.execute(
                "INSERT INTO horse_profile_templates ("
                + ", ".join(columns + ["owner_id"])
                + ") VALUES ("
                + placeholders
                + ")",
                (*args, owner),
            ).lastrowid

        assignments = ", ".join(
            column + "=?"
            for column in columns
        )

        conn.execute(
            "UPDATE horse_profile_templates SET "
            + assignments
            + ", updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND owner_id=?",
            (*args, template_id, owner),
        )

        return template_id
'''

MIGRATION = r'''
import sqlite3

columns = {
    row["name"]
    for row in conn.execute(
        "PRAGMA table_info(horse_profile_templates)"
    )
}

if "breeding_farm_id" not in columns:
    try:
        conn.execute(
            "ALTER TABLE horse_profile_templates "
            "ADD COLUMN breeding_farm_id INTEGER "
            "REFERENCES breeding_farms(id)"
        )

    except sqlite3.OperationalError:
        # Another session may have completed the migration.
        # Suppress only if the required column now exists.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(horse_profile_templates)"
            )
        }

        if "breeding_farm_id" not in columns:
            raise
'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# HORSE_TEMPLATE_BREEDING_FARM_V1"


def function(tree, name):
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(found) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(found)}."
        )

    return found[0]


def start_line(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in getattr(
                node,
                "decorator_list",
                [],
            )
        ]
    ) - 1


def patch_source(source):
    tree = ast.parse(source)

    if MARKER in source:
        return source, False

    if "# HORSE_PROFILE_TEMPLATES_V1" not in source:
        raise ValueError(
            "Install the Horse Templates feature first, "
            "including its widget-key installer repair."
        )

    configs = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_HT_FIELDS"
                for target in node.targets
            )
        )
    ]

    if (
        len(configs) != 1
        or not isinstance(configs[0].value, ast.Dict)
    ):
        raise ValueError(
            "Cannot identify the horse-template "
            "field configuration."
        )

    config = configs[0]
    fields = config.value

    names = [
        node.value
        if isinstance(node, ast.Constant)
        else None
        for node in fields.keys
    ]

    if set(names) != {
        "horse",
        "horse_owner",
        "stallion",
        "broodmare_sire",
        "trainer",
    }:
        raise ValueError(
            "Unexpected or partially modified "
            "horse-template fields."
        )

    position = names.index("horse_owner") + 1

    fields.keys.insert(
        position,
        ast.Constant(value="breeding_farm"),
    )

    fields.values.insert(
        position,
        ast.parse(
            '("Breeding farm", '
            '"breeding_farms", '
            '"breeding_farm_name")',
            mode="eval",
        ).body,
    )

    schema = function(tree, "_ht_schema")
    old_save = function(tree, "_ht_save")
    horse_input = function(tree, "_ht_horse_input")
    race = function(tree, "render_race_checklist_page")

    if (
        old_save.decorator_list
        or [
            argument.arg
            for argument in old_save.args.args
        ] != ["values", "template_id"]
    ):
        raise ValueError(
            "Unexpected horse-template save "
            "function signature."
        )

    farm_inputs = [
        node.value
        for node in ast.walk(race)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "selected_breeding_farm_idx"
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
        )
    ]

    horse_inputs = [
        node
        for node in ast.walk(race)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_ht_horse_input"
        )
    ]

    if (
        len(farm_inputs) != 1
        or len(horse_inputs) != 1
    ):
        raise ValueError(
            "Cannot uniquely identify the horse "
            "and breeding-farm selectors."
        )

    farm = farm_inputs[0]
    horse = horse_inputs[0]

    if (
        not isinstance(farm.func, ast.Name)
        or farm.func.id not in {
            "render_race_reference_input",
            "_ht_reference_input",
        }
    ):
        raise ValueError(
            "Unrecognized breeding-farm selector."
        )

    if farm.lineno <= horse.lineno:
        raise ValueError(
            "The horse selector must precede "
            "the breeding-farm selector."
        )

    keys = [
        keyword.value
        for keyword in farm.keywords
        if keyword.arg == "key"
    ]

    targets = [
        keyword.value
        for keyword in horse.keywords
        if keyword.arg == "target_keys"
    ]

    if (
        len(keys) != 1
        or len(targets) != 1
        or not isinstance(targets[0], ast.Dict)
    ):
        raise ValueError(
            "Cannot identify the existing "
            "horse-template autofill keys."
        )

    if any(
        isinstance(key, ast.Constant)
        and key.value == "breeding_farm"
        for key in targets[0].keys
    ):
        raise ValueError(
            "Breeding-farm autofill is already "
            "partially installed."
        )

    # Reuse the actual key expression from the farm selector.
    targets[0].keys.append(
        ast.Constant(value="breeding_farm")
    )

    targets[0].values.append(
        copy.deepcopy(keys[0])
    )

    farm.func = ast.Name(
        id="_ht_reference_input",
        ctx=ast.Load(),
    )

    schema.body.extend(
        ast.parse(MIGRATION).body
    )

    for node in ast.walk(horse_input):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            node.value = node.value.replace(
                "Reload the saved owner, stallion, "
                "broodmare sire and trainer "
                "into this draft only.",
                "Reload the saved owner, breeding farm, "
                "stallion, broodmare sire and trainer "
                "into this draft only.",
            )

    new_save = ast.parse(NEW_SAVE).body[0]

    edits = []

    for node in (
        config,
        schema,
        horse_input,
        race,
    ):
        ast.fix_missing_locations(node)

        text = ast.unparse(node) + "\n\n"

        if node is config:
            text = MARKER + "\n" + text

        edits.append(
            (
                start_line(node),
                node.end_lineno,
                text,
            )
        )

    edits.append(
        (
            start_line(old_save),
            old_save.end_lineno,
            NEW_SAVE.strip() + "\n\n",
        )
    )

    tree.body[
        tree.body.index(old_save)
    ] = new_save

    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(
            edits,
            edits[1:],
        )
    ):
        raise ValueError(
            "Overlapping source edits."
        )

    lines = source.splitlines(keepends=True)

    for begin, end, text in reversed(edits):
        lines[begin:end] = [text]

    updated = "".join(lines)

    compile(
        updated,
        "<horse-template-breeding-farm>",
        "exec",
    )

    if ast.dump(
        ast.parse(updated),
        include_attributes=False,
    ) != ast.dump(
        tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes outside the intended "
            "breeding-farm integration."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add breeding farm to horse templates "
            "and checklist autofill."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    app = Path(
        parser.parse_args().app_file
    ).resolve()

    if not app.is_file():
        raise SystemExit(
            f"Application file not found: {app}"
        )

    original = app.read_bytes()

    try:
        updated, changed = patch_source(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "Breeding farm is already installed "
            "in horse templates."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-horse-template-farm-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application changed during validation. Retry."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        encoding = (
            "utf-8-sig"
            if original.startswith(b"\xef\xbb\xbf")
            else "utf-8"
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="\n",
            dir=app.parent,
            prefix=f".{app.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated)

        shutil.copymode(app, temporary)

        if app.read_bytes() != original:
            raise RuntimeError(
                "Application changed before replacement. Retry."
            )

        temporary.replace(app)
        temporary = None

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            temporary.unlink()

    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print(
        "Breeding farm added to horse-template "
        "create/edit/save and Race Checklist autofill."
    )
    print(
        "Existing templates receive an empty "
        "breeding-farm default until edited."
    )
    print(
        "The nullable database column is added "
        "automatically on first feature use."
    )
    print(
        "Existing checklists are not rewritten."
    )
    print(
        "Restart Streamlit, open Horse Templates, "
        "choose a farm and save."
    )


if __name__ == "__main__":
    main()
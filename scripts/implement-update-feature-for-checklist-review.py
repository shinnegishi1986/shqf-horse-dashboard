# scripts/implement-update-feature-for-checklist-review.py
#
# Allows new reference names to be entered directly in the
# Checklist Review editor, without registering them first.
#
# Keeps existing selectors and adds optional New name fields.
# New names take priority over existing selector values.
#
# New reference records and checklist changes are committed
# together through the existing update_checklist transaction.
#
# Compatible with the previously supplied:
#   - Race Class feature
#   - Race-template venue/editor-loading feature
#   - Memo and bracket/horse-number table additions
#   - Blog features
#
# Creates a timestamped source backup.
# Does not change database records or schema while applying.
#
# Stop Streamlit before running:
#
# python scripts/implement-update-feature-for-checklist-review.py app.py

RUNTIME = r'''
# CHECKLIST_REVIEW_NEW_REFERENCES_V1

def _cru_tables():
    return {
        "horse_id": ("horses", "horse_name"),
        "horse_owner_id": ("horse_owners", "horse_owner_name"),
        "jockey_id": ("jockeys", "jockey_name"),
        "previous_jockey_id": ("jockeys", "jockey_name"),
        "trainer_id": ("trainers", "trainer_name"),
        "breeding_farm_id": ("breeding_farms", "breeding_farm_name"),
        "stallion_id": ("stallions", "stallion_name"),
        "broodmare_sire_id": ("stallions", "stallion_name"),
        "venue_id": ("venues", "venue_name"),
        "previous_venue_id": ("venues", "venue_name"),
        "race_name_id": ("race_names", "race_name"),
        "race_class_id": ("race_classes", "race_class_name"),
    }


def _cru_new_key(owner_id, entry_id, field):
    return f"cru_new_{owner_id}_{entry_id}_{field}"


def _cru_input(owner_id, entry_id, field, label):
    return st.text_input(
        "New " + label + " (optional)",
        max_chars=200,
        key=_cru_new_key(owner_id, entry_id, field),
        help=(
            "Leave blank to use the selection above. "
            "A new name takes priority and is registered "
            "when Update Checklist succeeds."
        ),
    )


def _cru_mark_clear(owner_id, entry_id):
    st.session_state[
        f"cru_clear_{owner_id}_{entry_id}"
    ] = True


def _cru_prepare(owner_id, entry_id, widget_keys):
    clear_key = f"cru_clear_{owner_id}_{entry_id}"

    if st.session_state.pop(clear_key, False):
        for field in _cru_tables():
            st.session_state.pop(
                _cru_new_key(owner_id, entry_id, field),
                None,
            )

        # Reset keyed reference selectors before they are rendered.
        # New reference items can change their option indexes.
        for key in widget_keys:
            st.session_state.pop(key, None)


def _cru_clear_for_template(owner_id, entry_id, values):
    # Loading a template should not be overridden by stale text
    # previously typed into the race-name or venue fields.
    for editor_field, field in (
        ("edit_race_idx", "race_name_id"),
        ("edit_venue_idx", "venue_id"),
    ):
        if editor_field in values:
            st.session_state[
                _cru_new_key(owner_id, entry_id, field)
            ] = ""

    st.session_state[
        _cru_new_key(owner_id, entry_id, "race_class_id")
    ] = ""


def _cru_resolve(
    cursor,
    owner_id,
    checklist_id,
    changes,
    current,
):
    if changes is None:
        return current

    if (
        not isinstance(changes, dict)
        or set(changes) - set(current)
    ):
        raise ValueError("Invalid new-reference fields.")

    if any(
        not isinstance(value, str)
        for value in changes.values()
    ):
        raise ValueError(
            "New reference names must be text."
        )

    if not any(
        value.strip()
        for value in changes.values()
    ):
        return current

    if not cursor.execute(
        "SELECT 1 FROM checklists "
        "WHERE owner_id=? AND id=?",
        (owner_id, checklist_id),
    ).fetchone():
        raise ValueError(
            "Checklist is unavailable for this account."
        )

    result = dict(current)
    cache = {}

    for field, value in changes.items():
        name = value.strip()

        if not name:
            continue

        if len(name) > 200:
            raise ValueError(
                "New reference names must be "
                "200 characters or fewer."
            )

        # Table/column names come only from this fixed whitelist.
        table, column = _cru_tables()[field]

        if table not in cache:
            rows = cursor.execute(
                f"SELECT id,{column} FROM {table} "
                "WHERE owner_id=? ORDER BY id",
                (owner_id,),
            ).fetchall()

            cache[table] = {}

            for row in rows:
                normalized = (
                    str(row[column]).strip().casefold()
                )

                cache[table].setdefault(
                    normalized,
                    row["id"],
                )

        normalized = name.casefold()
        item_id = cache[table].get(normalized)

        if item_id is None:
            cursor.execute(
                f"INSERT INTO {table}(owner_id,{column}) "
                "VALUES (?,?)",
                (owner_id, name),
            )

            item_id = cursor.lastrowid
            cache[table][normalized] = item_id

        result[field] = item_id

    return result

'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# CHECKLIST_REVIEW_NEW_REFERENCES_V1"

SPECS = [
    ("edit_horse_idx", "horse_id", "Horse"),
    ("edit_horse_owner_idx", "horse_owner_id", "Horse Owner"),
    ("edit_jockey_idx", "jockey_id", "Jockey"),
    (
        "edit_previous_jockey_idx",
        "previous_jockey_id",
        "Previous Jockey",
    ),
    ("edit_trainer_idx", "trainer_id", "Trainer"),
    (
        "edit_breeding_farm_idx",
        "breeding_farm_id",
        "Breeding Farm",
    ),
    ("edit_stallion_idx", "stallion_id", "Stallion"),
    (
        "edit_broodmare_sire_idx",
        "broodmare_sire_id",
        "Broodmare Sire",
    ),
    ("edit_venue_idx", "venue_id", "Venue"),
    (
        "edit_previous_venue_idx",
        "previous_venue_id",
        "Previous Venue",
    ),
    ("edit_race_idx", "race_name_id", "Race Name"),
]


def find_function(tree, name):
    rows = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(rows) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(rows)}."
        )

    return rows[0]


def assignment_names(node):
    if not isinstance(node, ast.Assign):
        return set()

    return {
        item.id
        for target in node.targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name)
    }


def definition_start(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


class EditorTransformer(ast.NodeTransformer):
    def __init__(self, specs):
        self.specs = {
            widget: (field, label)
            for widget, field, label in specs
        }

        self.found = set()
        self.keys = []
        self.saves = 0
        self.restores = 0

    def visit_FunctionDef(self, node):
        # Do not transform nested helper functions.
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)

        matches = set(self.specs).intersection(
            assignment_names(node)
        )

        if not matches:
            return node

        if (
            len(matches) != 1
            or not isinstance(node.value, ast.Call)
        ):
            raise ValueError(
                "Unexpected reference widget assignment."
            )

        widget = next(iter(matches))
        field, label = self.specs[widget]

        if field in self.found:
            raise ValueError(
                f"Multiple reference widgets found for {field}."
            )

        self.found.add(field)
        call = node.value

        key = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "key"
            ),
            None,
        )

        if (
            key is None
            and isinstance(call.func, ast.Name)
            and call.func.id == "_rf_class_select"
        ):
            key = (
                call.args[1]
                if len(call.args) > 1
                else None
            )

        if key is not None:
            self.keys.append(copy.deepcopy(key))

        addition = ast.parse(
            f"cru_new_{field} = _cru_input("
            f"owner_id, entry['id'], {field!r}, {label!r})"
        ).body

        return [node] + addition

    def visit_Call(self, node):
        self.generic_visit(node)

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "update_checklist"
        ):
            fields = [
                field
                for field, label in self.specs.values()
            ]

            node.keywords.append(
                ast.keyword(
                    arg="_review_new_references",
                    value=ast.Dict(
                        keys=[
                            ast.Constant(field)
                            for field in fields
                        ],
                        values=[
                            ast.Name(
                                id="cru_new_" + field,
                                ctx=ast.Load(),
                            )
                            for field in fields
                        ],
                    ),
                )
            )

            self.saves += 1

        return node

    def visit_Expr(self, node):
        self.generic_visit(node)

        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id
            == "_queue_review_update_filter_restore"
        ):
            self.restores += 1

            return [node] + ast.parse(
                "_cru_mark_clear(owner_id, entry['id'])"
            ).body

        return node


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    editor = find_function(
        tree,
        "render_checklist_editor",
    )

    update = find_function(
        tree,
        "update_checklist",
    )

    helper_names = {
        node.name
        for node in ast.parse(RUNTIME).body
        if isinstance(node, ast.FunctionDef)
    }

    existing = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    if helper_names & existing:
        raise ValueError(
            "Conflicting checklist-update helper names "
            "already exist."
        )

    modified = {
        editor.name: editor,
        update.name: update,
    }

    original_spans = {
        name: (
            definition_start(function),
            function.end_lineno,
        )
        for name, function in modified.items()
    }

    arguments = {
        argument.arg
        for argument in (
            update.args.args
            + update.args.kwonlyargs
        )
    }

    if "_review_new_references" in arguments:
        raise ValueError(
            "The update function already has "
            "new-reference support."
        )

    specs = list(SPECS)

    if "race_class_id" in arguments:
        specs.append(
            (
                "rf_editor_class_id",
                "race_class_id",
                "Race Class",
            )
        )

    fields = [
        field
        for widget, field, label in specs
    ]

    if not set(fields).issubset(arguments):
        raise ValueError(
            "The update function has unexpected "
            "reference arguments."
        )

    visitor = EditorTransformer(specs)
    body = []

    for node in editor.body:
        result = visitor.visit(node)

        body.extend(
            result
            if isinstance(result, list)
            else [result]
        )

    editor.body = body

    if (
        visitor.found != set(fields)
        or visitor.saves != 1
        or visitor.restores != 1
    ):
        raise ValueError(
            "Cannot safely identify all editor widgets, "
            "the save call, and filter restoration."
        )

    editor.body.insert(
        0,
        ast.Expr(
            value=ast.Call(
                func=ast.Name(
                    id="_cru_prepare",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Name(
                        id="owner_id",
                        ctx=ast.Load(),
                    ),
                    ast.parse(
                        "entry['id']",
                        mode="eval",
                    ).body,
                    ast.List(
                        elts=visitor.keys,
                        ctx=ast.Load(),
                    ),
                ],
                keywords=[],
            )
        ),
    )

    update.args.kwonlyargs.append(
        ast.arg(arg="_review_new_references")
    )

    update.args.kw_defaults.append(
        ast.Constant(None)
    )

    # Resolve new horse/reference IDs before checking for an
    # existing checklist with the same horse and race date.
    locations = []

    for node in ast.walk(update):
        if isinstance(node, ast.Try):
            for index, statement in enumerate(node.body):
                if (
                    isinstance(statement, ast.If)
                    and ast.unparse(statement.test)
                    == "horse_id is not None"
                ):
                    locations.append((node, index))

    if len(locations) != 1:
        raise ValueError(
            "Cannot locate the pre-duplicate-check "
            "reference resolution point."
        )

    transaction, index = locations[0]

    current = (
        "{"
        + ", ".join(
            f"{field!r}: {field}"
            for field in fields
        )
        + "}"
    )

    resolution_code = (
        "_cru_ids = _cru_resolve("
        "cursor, owner_id, checklist_id, "
        "_review_new_references, "
        + current
        + ")\n"
    )

    resolution_code += "\n".join(
        f"{field} = _cru_ids[{field!r}]"
        for field in fields
    )

    transaction.body[index:index] = ast.parse(
        resolution_code
    ).body

    if any(
        handler.type is None
        or "ValueError" in ast.unparse(handler.type)
        for handler in transaction.handlers
    ):
        raise ValueError(
            "An unexpected ValueError handler requires "
            "a source-specific adjustment."
        )

    validation_handler = ast.parse(
        "try:\n"
        "    pass\n"
        "except ValueError as error:\n"
        "    conn.rollback()\n"
        "    return False, str(error)\n"
    ).body[0].handlers[0]

    transaction.handlers.insert(
        0,
        validation_handler,
    )

    # Preserve compatibility with loading race templates
    # into the Checklist Review editor.
    if "_rf_venue_load_editor" in existing:
        loader = find_function(
            tree,
            "_rf_venue_load_editor",
        )

        original_spans[loader.name] = (
            definition_start(loader),
            loader.end_lineno,
        )

        sites = [
            (node, index)
            for node in ast.walk(loader)
            if isinstance(node, ast.Try)
            for index, statement in enumerate(node.body)
            if (
                isinstance(statement, ast.Assign)
                and "message" in assignment_names(statement)
            )
        ]

        if len(sites) != 1:
            raise ValueError(
                "Cannot safely integrate new-name clearing "
                "with template loading."
            )

        node, position = sites[0]

        node.body[position:position] = ast.parse(
            "_cru_clear_for_template("
            "owner_id, entry_id, values)"
        ).body

        modified[loader.name] = loader

    edits = []

    for name, node in modified.items():
        ast.fix_missing_locations(node)
        start, end = original_spans[name]

        edits.append(
            (
                start,
                end,
                ast.unparse(node) + "\n\n",
            )
        )

    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(edits, edits[1:])
    ):
        raise ValueError(
            "Overlapping source edits."
        )

    lines = source.splitlines(keepends=True)

    for start, end, text in reversed(edits):
        lines[start:end] = [text]

    intermediate = "".join(lines)

    first = next(
        node
        for node in ast.parse(intermediate).body
        if isinstance(
            node,
            (ast.FunctionDef, ast.ClassDef),
        )
    )

    lines = intermediate.splitlines(keepends=True)

    lines.insert(
        definition_start(first),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<checklist-review-new-references>",
        "exec",
    )

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in (
                    helper_names | set(modified)
                )
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside checklist "
            "update integration points."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Register new reference names while updating "
            "a checklist in Checklist Review."
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
        updated, changed = patch_application(
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
            "Checklist Review new-reference support "
            "is already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-review-new-references-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed during validation. "
                "Retry the patch."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
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
                "Application source changed before replacement. "
                "Retry the patch."
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
    print("Syntax and change-scope validation passed.")
    print(
        "Restart Streamlit and open a "
        "Checklist Review editor."
    )
    print(
        "New name fields take priority over "
        "their existing dropdown selections."
    )
    print(
        "Reference creation and checklist update share "
        "the same database transaction."
    )
    print(
        "No database records or schema were changed "
        "by this patch script."
    )
    print(
        "Interactive browser testing remains required."
    )


if __name__ == "__main__":
    main()
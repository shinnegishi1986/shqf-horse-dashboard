# scripts/horse-template-in-race-checklist
#
# Requires the installed Horse Templates feature.
#
# Adds a saved horse-template selector and Load button
# to Race Checklist, alongside the existing race-template loader.
#
# Loads every configured horse-template field:
#   Horse, Horse Owner, Stallion, Broodmare Sire, Trainer,
#   and Breeding Farm when installed.
#
# Preserves actual widget-key expressions.
# Does not save a checklist or overwrite race-specific fields.
# Templates are scoped to the signed-in account.
# Creates a timestamped app.py backup.
#
# Stop Streamlit before running:
#
# python scripts/horse-template-in-race-checklist app.py

RUNTIME = r'''
# HORSE_TEMPLATE_CHECKLIST_PICKER_V1

def _htc_load(owner_id, template_id, target_keys):
    from contextlib import closing
    import sqlite3

    try:
        if _ht_owner() != owner_id:
            raise PermissionError(
                "Sign in again before loading a horse template."
            )

        if set(target_keys) != set(_HT_FIELDS):
            raise ValueError(
                "The horse-template fields and checklist "
                "loader do not match."
            )

        with closing(get_db_connection()) as conn, conn:
            _ht_schema(conn)

            row = conn.execute(
                "SELECT * FROM horse_profile_templates "
                "WHERE id=? AND owner_id=?",
                (template_id, owner_id),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "This horse template is no longer available."
                )

            names = _ht_names(
                conn,
                owner_id,
                dict(row),
            )

        if not names.get("horse"):
            raise ValueError(
                "The template's horse is no longer registered. "
                "Edit the template first."
            )

        # Resolve all values before changing any draft fields.
        updates = {
            target_keys[field]: names.get(field) or None
            for field in _HT_FIELDS
        }

        # This callback runs before widgets are rendered on rerun.
        for key, value in updates.items():
            st.session_state[key] = value

        # Keep the existing automatic horse-default loader in sync.
        st.session_state[
            f"ht_last_horse_{owner_id}"
        ] = (
            target_keys["horse"],
            names["horse"].casefold(),
        )

        st.session_state[
            f"htc_notice_{owner_id}"
        ] = "Horse template loaded."

    except (PermissionError, ValueError) as error:
        st.session_state[
            f"htc_error_{owner_id}"
        ] = str(error)

    except sqlite3.Error:
        st.session_state[
            f"htc_error_{owner_id}"
        ] = (
            "Could not load the horse template. Try again."
        )


def _htc_checklist_loader(owner_id, target_keys):
    from contextlib import closing

    if _ht_owner() != owner_id:
        st.error(
            "Administrator or other-user templates "
            "cannot be loaded into this account."
        )
        return

    notice = st.session_state.pop(
        f"htc_notice_{owner_id}",
        None,
    )

    error = st.session_state.pop(
        f"htc_error_{owner_id}",
        None,
    )

    if notice:
        st.success(notice)

    if error:
        st.error(error)

    with st.expander(
        "Load Horse Template",
        expanded=False,
    ):
        with closing(get_db_connection()) as conn, conn:
            _ht_schema(conn)

            rows = conn.execute(
                "SELECT t.id, h.horse_name "
                "FROM horse_profile_templates t "
                "JOIN horses h "
                "ON h.id=t.horse_id "
                "AND h.owner_id=t.owner_id "
                "WHERE t.owner_id=? "
                "ORDER BY h.horse_name COLLATE NOCASE, t.id",
                (owner_id,),
            ).fetchall()

        if not rows:
            st.info(
                "Create a horse template "
                "from the Horse Templates menu."
            )
            return

        lookup = {
            row["id"]: str(row["horse_name"])
            for row in rows
        }

        prefix = (
            f"htc_picker_{owner_id}_"
            f"{target_keys['horse']}"
        )

        select_key = prefix + "_selection"

        if (
            select_key in st.session_state
            and st.session_state[select_key] not in lookup
        ):
            st.session_state[select_key] = None

        selected = st.selectbox(
            "Horse template",
            [None] + list(lookup),
            index=None,
            key=select_key,
            format_func=lambda item: (
                "(Select a template)"
                if item is None
                else lookup[item]
            ),
            placeholder="Select a saved horse template",
        )

        st.caption(
            "Load fills horse details only. "
            "It does not save a checklist."
        )

        st.button(
            "Load Horse Template",
            key=prefix + "_load",
            disabled=selected is None,
            on_click=_htc_load,
            args=(
                owner_id,
                selected,
                target_keys,
            ),
        )

'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# HORSE_TEMPLATE_CHECKLIST_PICKER_V1"


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
            for decorator in node.decorator_list
        ]
    ) - 1


def patch_source(source):
    tree = ast.parse(source)

    if MARKER in source:
        function(tree, "_htc_load")
        function(tree, "_htc_checklist_loader")
        return source, False

    if "# HORSE_PROFILE_TEMPLATES_V1" not in source:
        raise ValueError(
            "Install the Horse Templates feature "
            "before adding this selector."
        )

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name.startswith("_htc_")
        for node in tree.body
    ):
        raise ValueError(
            "Conflicting horse-template picker "
            "helpers already exist."
        )

    for name in (
        "_ht_owner",
        "_ht_schema",
        "_ht_names",
        "get_db_connection",
    ):
        function(tree, name)

    configs = [
        node.value
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

    if len(configs) != 1:
        raise ValueError(
            "Cannot identify the horse-template "
            "field configuration."
        )

    fields = ast.literal_eval(configs[0])

    required = {
        "horse",
        "horse_owner",
        "stallion",
        "broodmare_sire",
        "trainer",
    }

    if (
        not isinstance(fields, dict)
        or not required <= set(fields)
        or set(fields) - required - {"breeding_farm"}
    ):
        raise ValueError(
            "Unrecognized horse-template fields."
        )

    race = function(
        tree,
        "render_race_checklist_page",
    )

    main = function(tree, "main")

    mapping = {
        "horse": "selected_horse_idx",
        "horse_owner": "selected_horse_owner_idx",
        "stallion": "selected_stallion_idx",
        "broodmare_sire": "selected_broodmare_sire_idx",
        "trainer": "selected_trainer_idx",
        "breeding_farm": "selected_breeding_farm_idx",
    }

    target_keys = {}
    horse_call = None

    for field in fields:
        matches = [
            node.value
            for node in ast.walk(race)
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == mapping[field]
                    for target in node.targets
                )
                and isinstance(node.value, ast.Call)
            )
        ]

        if len(matches) != 1:
            raise ValueError(
                f"Cannot identify the {field} "
                "reference input."
            )

        call = matches[0]

        if (
            not isinstance(call.func, ast.Name)
            or call.func.id not in {
                "_ht_horse_input",
                "_ht_reference_input",
                "render_race_reference_input",
            }
        ):
            raise ValueError(
                "Unexpected reference selector "
                f"for {field}."
            )

        keys = [
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "key"
        ]

        if len(keys) != 1:
            raise ValueError(
                "Cannot identify the widget key "
                f"for {field}."
            )

        target_keys[field] = copy.deepcopy(keys[0])

        if field == "horse":
            horse_call = call

    positions = [
        index
        for index, node in enumerate(race.body)
        if any(
            child is horse_call
            for child in ast.walk(node)
        )
    ]

    if len(positions) != 1:
        raise ValueError(
            "Cannot determine a safe loader position "
            "before the horse widgets."
        )

    loader = ast.Expr(
        value=ast.Call(
            func=ast.Name(
                id="_htc_checklist_loader",
                ctx=ast.Load(),
            ),
            args=[
                ast.Name(
                    id="owner_id",
                    ctx=ast.Load(),
                ),
                ast.Dict(
                    keys=[
                        ast.Constant(value=field)
                        for field in target_keys
                    ],
                    values=list(target_keys.values()),
                ),
            ],
            keywords=[],
        )
    )

    race.body.insert(
        positions[0],
        loader,
    )

    ast.fix_missing_locations(race)

    helpers = ast.parse(RUNTIME).body

    index = tree.body.index(main)
    tree.body[index:index] = helpers

    edits = [
        (
            start_line(race),
            race.end_lineno,
            ast.unparse(race) + "\n\n",
        ),
        (
            start_line(main),
            start_line(main),
            RUNTIME.strip() + "\n\n",
        ),
    ]

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
        "<horse-template-checklist-picker>",
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
            "Unexpected changes outside the "
            "horse-template selector integration."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add a saved horse-template selector "
            "to Race Checklist."
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
            "The Race Checklist horse-template "
            "selector is already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-horse-template-picker-{stamp}.bak"
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
        "Added Load Horse Template "
        "to Race Checklist."
    )
    print(
        "Loads every configured horse-template field, "
        "including breeding farm when installed."
    )
    print(
        "Race-template loading, checklist saving, "
        "menus and permissions were preserved."
    )
    print(
        "Restart Streamlit and expand "
        "Load Horse Template in Race Checklist."
    )


if __name__ == "__main__":
    main()
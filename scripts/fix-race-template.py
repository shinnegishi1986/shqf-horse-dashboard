# scripts/fix-race-template.py
#
# Replaces separate race-template inputs:
#   - Existing race name
#   - New race name
#
# With one selector:
#   - Select an existing suggestion
#   - Or type a new race name and press Enter
#
# New names are registered when the template is successfully saved.
#
# Also updates the template edit form if _rt_manage is installed.
#
# Preserves:
#   - Existing template save/update database logic
#   - Venue and race-class fields
#   - Template IDs and blog associations
#   - Template edit/delete controls
#   - Checklist Review, monthly comparisons, and other pages
#
# Native Streamlit selectbox accept_new_options support is required.
# No extra text-input fallback is added.
#
# Creates a timestamped source backup.
# Does not modify database records or schema while applying.
#
# Stop Streamlit before running:
#
#   python scripts/fix-race-template.py app.py

RUNTIME = r'''
# RACE_TEMPLATE_SINGLE_RACE_NAME_V1

def _rtn_require_native():
    import inspect

    try:
        supported = (
            "accept_new_options"
            in inspect.signature(st.selectbox).parameters
        )
    except (TypeError, ValueError):
        supported = False

    if not supported:
        st.error(
            "Race-name entry requires a Streamlit version "
            "supporting selectbox accept_new_options. "
            "Upgrade and restart: "
            "python -m pip install --upgrade streamlit"
        )
        st.stop()


def _rtn_input(owner_id, key, current_id=None):
    rows = get_user_race_names(owner_id)

    options = [None]

    for row in rows:
        name = str(row["race_name"]).strip()

        if name and name not in options:
            options.append(name)

    current = next(
        (
            str(row["race_name"]).strip()
            for row in rows
            if row["id"] == current_id
        ),
        None,
    )

    if current not in options:
        current = None

    selected = st.selectbox(
        "Race name",
        options,
        index=(
            None
            if key in st.session_state
            else options.index(current)
        ),
        format_func=lambda value: (
            "(Select or type a race name)"
            if value is None
            else value
        ),
        key=key,
        accept_new_options=True,
        placeholder=(
            "Select a saved race name or type a new one"
        ),
        help=(
            "Select a suggestion, or type a new name "
            "and press Enter. New race names are registered "
            "when the template is successfully saved."
        ),
    )

    if selected is None or not str(selected).strip():
        return None, ""

    name = str(selected).strip()

    exact = [
        row
        for row in rows
        if str(row["race_name"]).strip() == name
    ]

    matches = exact or [
        row
        for row in rows
        if str(row["race_name"]).strip().casefold()
        == name.casefold()
    ]

    if matches:
        row = next(
            (
                row
                for row in matches
                if row["id"] == current_id
            ),
            matches[0],
        )

        return row["id"], ""

    # Existing save/update functions register this new name
    # inside their database transaction.
    return None, name

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# RACE_TEMPLATE_SINGLE_RACE_NAME_V1"


def find_function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(matches)}."
        )

    return matches[0]


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


class SingleNameTransformer(ast.NodeTransformer):
    def __init__(self, editing):
        self.editing = editing
        self.selectors = 0
        self.inputs = 0

    def visit_FunctionDef(self, node):
        # Do not transform nested helper functions.
        return node

    def visit_Assign(self, node):
        names = assignment_names(node)
        value = node.value

        if "name_id" in names:
            if (
                names != {"name_id"}
                or not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and isinstance(
                        value.func.value,
                        ast.Name,
                    )
                    and value.func.value.id == "st"
                    and value.func.attr == "selectbox"
                )
            ):
                raise ValueError(
                    "Unexpected race-name selector structure."
                )

            self.selectors += 1

            if self.editing:
                code = (
                    "name_id, new_name = _rtn_input("
                    "owner_id, prefix + '_race_name', initial_name)"
                )
            else:
                code = (
                    "name_id, name = _rtn_input("
                    "owner_id, f'rtn_create_{owner_id}')"
                )

            return ast.parse(code).body[0]

        field = (
            "new_name"
            if self.editing
            else "name"
        )

        if field in names:
            if (
                names != {field}
                or not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and isinstance(
                        value.func.value,
                        ast.Name,
                    )
                    and value.func.value.id == "st"
                    and value.func.attr == "text_input"
                )
            ):
                raise ValueError(
                    "Unexpected separate new-race-name "
                    "input structure."
                )

            self.inputs += 1

            # Remove the separate text input.
            return None

        return self.generic_visit(node)


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    page = find_function(
        tree,
        "_rf_templates_page",
    )

    find_function(
        tree,
        "get_user_race_names",
    )

    save = find_function(
        tree,
        "_rf_save_template",
    )

    save_arguments = {
        argument.arg
        for argument in (
            save.args.args
            + save.args.kwonlyargs
        )
    }

    if not {"name_id", "new_name"}.issubset(
        save_arguments
    ):
        raise ValueError(
            "Unexpected template save interface."
        )

    helpers = {
        node.name
        for node in ast.parse(RUNTIME).body
        if isinstance(node, ast.FunctionDef)
    }

    existing = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    if helpers & existing:
        raise ValueError(
            "Conflicting single-race-name helpers "
            "already exist."
        )

    targets = [
        (page, False),
    ]

    if "_rt_manage" in existing:
        find_function(
            tree,
            "_rt_update",
        )

        targets.append(
            (
                find_function(tree, "_rt_manage"),
                True,
            )
        )

    edits = []

    for function, editing in targets:
        start = definition_start(function)
        end = function.end_lineno

        visitor = SingleNameTransformer(editing)
        body = []

        for statement in function.body:
            result = visitor.visit(statement)

            if result is not None:
                body.extend(
                    result
                    if isinstance(result, list)
                    else [result]
                )

        if (
            visitor.selectors,
            visitor.inputs,
        ) != (1, 1):
            raise ValueError(
                "Cannot uniquely identify the two "
                f"race-name inputs in {function.name}."
            )

        function.body = (
            ast.parse(
                "_rtn_require_native()"
            ).body
            + body
        )

        ast.fix_missing_locations(function)

        edits.append(
            (
                start,
                end,
                ast.unparse(function) + "\n\n",
            )
        )

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

    lines = source.splitlines(
        keepends=True
    )

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

    lines = intermediate.splitlines(
        keepends=True
    )

    lines.insert(
        definition_start(first),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<race-template-single-name>",
        "exec",
    )

    permitted = helpers | {
        function.name
        for function, editing in targets
    }

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside race-name "
            "form integration points."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid single-race-name patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Replace separate race-template name inputs "
            "with one editable suggestion selector."
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
            "Single-input race-template names "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-single-template-name-{stamp}.bak"
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

        shutil.copymode(
            app,
            temporary,
        )

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
    print("Syntax and AST change-scope validation passed.")
    print(
        "Race Templates now uses one race-name selector "
        "with suggestions and typed new names."
    )
    print(
        "The template edit form was updated too, "
        "if installed."
    )
    print(
        "New names are registered only when "
        "Save Race Template / Save Template Changes succeeds."
    )
    print(
        "Existing database save logic, venue fields, "
        "edit/delete controls, and other pages were preserved."
    )
    print(
        "No database records or schema were changed "
        "by this patch script."
    )
    print(
        "Restart Streamlit. Native selectbox "
        "accept_new_options support is required."
    )
    print(
        "Interactive browser testing remains required."
    )


if __name__ == "__main__":
    main()
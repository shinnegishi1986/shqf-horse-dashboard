# scripts/fix-weired-stuff.py
#
# Changes:
#   1. Checklist Review becomes the first page after login.
#   2. Checklist Review becomes the first sidebar menu option.
#   3. Removes the Lightweight mode checkbox.
#   4. Restores interactive stacked charts and the weight chart.
#   5. Preserves touch tooltips, dark chart styling, and existing filters.
#
# Also supports the persistent-login patch:
#   Restored logins open Checklist Review.
#
# Run:
#   python scripts/fix-weired-stuff.py
#
# Or specify the application file:
#   python scripts/fix-weired-stuff.py app.py
#
# IMPORTANT:
#   Removing Lightweight mode does not fix browser compatibility problems
#   that prevent Streamlit itself from loading.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# REVIEW_FIRST_REMOVE_LIGHTWEIGHT_MODE_V1"

LIGHTWEIGHT_HELPERS = {
    "_older_device_lightweight_enabled",
    "render_older_device_settings",
    "_older_device_render_stacked_summary",
    "_older_device_vega_lite_chart",
}


def find_function(tree, name, required=True):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if not matches and not required:
        return None

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {name} function; found {len(matches)}."
        )

    return matches[0]


def is_named_call(node, name):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def find_navigation(main_function):
    matches = []

    for node in ast.walk(main_function):
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name)
            and target.id == "page"
            for target in node.targets
        ):
            continue

        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "radio"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "sidebar"
            and isinstance(call.func.value.value, ast.Name)
            and call.func.value.value.id == "st"
        ):
            matches.append(call)

    if len(matches) != 1:
        raise ValueError(
            "Could not uniquely identify the sidebar page navigation."
        )

    call = matches[0]

    key_values = [
        keyword.value
        for keyword in call.keywords
        if keyword.arg == "key"
    ]

    if key_values:
        if not (
            len(key_values) == 1
            and isinstance(key_values[0], ast.Constant)
            and isinstance(key_values[0].value, str)
        ):
            raise ValueError(
                "The navigation key must be a constant string."
            )

        navigation_key = key_values[0].value
    else:
        navigation_key = "app_navigation_page"

        call.keywords.append(
            ast.keyword(
                arg="key",
                value=ast.Constant(value=navigation_key),
            )
        )

    if len(call.args) >= 2:
        options = call.args[1]
    else:
        options = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "options"
            ),
            None,
        )

    if not (
        isinstance(options, (ast.List, ast.Tuple))
        and all(
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            for item in options.elts
        )
    ):
        raise ValueError(
            "Expected a literal list of sidebar page names."
        )

    page_names = [item.value for item in options.elts]

    if page_names.count("Checklist Review") != 1:
        raise ValueError(
            "Could not uniquely identify the Checklist Review menu option."
        )

    page_names.remove("Checklist Review")
    page_names.insert(0, "Checklist Review")

    options.elts = [
        ast.Constant(value=name)
        for name in page_names
    ]

    # Keep the first option as the radio's default.
    for keyword in call.keywords:
        if keyword.arg == "index":
            keyword.value = ast.Constant(value=0)

    return navigation_key


class RemoveLightweightCalls(ast.NodeTransformer):
    def visit_Expr(self, node):
        if is_named_call(
            node.value,
            "render_older_device_settings",
        ):
            return None

        return self.generic_visit(node)

    def visit_Call(self, node):
        node = self.generic_visit(node)

        if is_named_call(
            node,
            "_older_device_vega_lite_chart",
        ):
            node.func = ast.Attribute(
                value=ast.Name(id="st", ctx=ast.Load()),
                attr="vega_lite_chart",
                ctx=ast.Load(),
            )

        return node


def remove_stacked_lightweight_guard(function):
    function.body = [
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.If)
            and is_named_call(
                statement.test,
                "_older_device_lightweight_enabled",
            )
        )
    ]


def remove_touch_histogram_lightweight_guard(function):
    # Remove only the compatibility branch previously added to the
    # touch-enabled weight histogram helper.
    new_body = []

    for statement in function.body:
        if isinstance(statement, ast.Assign):
            targets = {
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            }

            if targets & {
                "lightweight_check",
                "lightweight_renderer",
            }:
                continue

        if isinstance(statement, ast.If):
            referenced_names = {
                node.id
                for node in ast.walk(statement.test)
                if isinstance(node, ast.Name)
            }

            if referenced_names & {
                "lightweight_check",
                "lightweight_renderer",
            }:
                continue

        new_body.append(statement)

    function.body = new_body


class SetReviewAfterLogin(ast.NodeTransformer):
    def __init__(self, navigation_key):
        self.navigation_key = navigation_key
        self.count = 0

    def visit_Assign(self, node):
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and node.targets[0].attr == "user_id"
            and isinstance(node.targets[0].value, ast.Attribute)
            and node.targets[0].value.attr == "session_state"
            and isinstance(node.targets[0].value.value, ast.Name)
            and node.targets[0].value.value.id == "st"
            and isinstance(node.value, ast.Name)
            and node.value.id == "user_id"
        ):
            self.count += 1

            return [
                node,
                ast.parse(
                    f"st.session_state[{self.navigation_key!r}] "
                    '= "Checklist Review"'
                ).body[0],
            ]

        return node


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    main_function = find_function(tree, "main")
    login_function = find_function(tree, "render_login_page")

    navigation_key = find_navigation(main_function)

    changed_functions = {
        "main",
        "render_login_page",
    }

    stacked_renderer = find_function(
        tree,
        "_render_review_stacked_count_chart",
        required=False,
    )

    if stacked_renderer is not None:
        remove_stacked_lightweight_guard(stacked_renderer)
        changed_functions.add(stacked_renderer.name)

    touch_renderer = find_function(
        tree,
        "_render_touch_weight_histogram",
        required=False,
    )

    if touch_renderer is not None:
        remove_touch_histogram_lightweight_guard(touch_renderer)
        changed_functions.add(touch_renderer.name)

    weight_renderer = find_function(
        tree,
        "render_review_weight_standard_distribution",
        required=False,
    )

    if weight_renderer is not None:
        changed_functions.add(weight_renderer.name)

    cleaner = RemoveLightweightCalls()

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in changed_functions
        ):
            cleaner.visit(node)

    login_transformer = SetReviewAfterLogin(navigation_key)
    login_transformer.visit(login_function)

    if login_transformer.count != 1:
        raise ValueError(
            "Could not uniquely identify the successful login assignment."
        )

    # Ensure a fresh session defaults to Checklist Review.
    setup = ast.parse(
        f"""
_review_was_logged_in = bool(
    st.session_state.get("logged_in", False)
)
st.session_state.setdefault(
    {navigation_key!r},
    "Checklist Review",
)
"""
    ).body

    setup_position = 0

    if (
        main_function.body
        and isinstance(main_function.body[0], ast.Expr)
        and isinstance(main_function.body[0].value, ast.Constant)
        and isinstance(main_function.body[0].value.value, str)
    ):
        setup_position = 1

    main_function.body[setup_position:setup_position] = setup

    bootstrap_positions = [
        index
        for index, statement in enumerate(main_function.body)
        if (
            isinstance(statement, ast.Expr)
            and is_named_call(
                statement.value,
                "_persistent_login_bootstrap",
            )
        )
    ]

    if len(bootstrap_positions) > 1:
        raise ValueError(
            "Unexpected duplicate persistent-login initialization."
        )

    if bootstrap_positions:
        restore_navigation = ast.parse(
            f"""
if (
    not _review_was_logged_in
    and st.session_state.get("logged_in", False)
):
    st.session_state[{navigation_key!r}] = "Checklist Review"
"""
        ).body

        position = bootstrap_positions[0] + 1
        main_function.body[position:position] = restore_navigation

    # Replace only affected functions and remove obsolete helpers.
    lines = source.splitlines(keepends=True)
    edits = []

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        if node.name in LIGHTWEIGHT_HELPERS:
            if node.decorator_list:
                raise ValueError(
                    f"Unexpected decorators on {node.name}."
                )

            edits.append(
                (node.lineno - 1, node.end_lineno, "")
            )

        elif node.name in changed_functions:
            if node.decorator_list:
                raise ValueError(
                    f"Unexpected decorators on {node.name}."
                )

            ast.fix_missing_locations(node)
            replacement = ast.unparse(node) + "\n\n"

            if node.name == "main":
                replacement = PATCH_MARKER + "\n" + replacement

            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    replacement,
                )
            )

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement] if replacement else []

    updated = "".join(lines)

    compile(updated, "<review-first-without-lightweight-mode>", "exec")

    updated_tree = ast.parse(updated)

    # Reject any remaining calls to deleted helpers.
    remaining_calls = {
        node.func.id
        for node in ast.walk(updated_tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in LIGHTWEIGHT_HELPERS
        )
    }

    if remaining_calls:
        raise ValueError(
            "Unresolved lightweight helper calls remain: "
            + ", ".join(sorted(remaining_calls))
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid patch marker.")

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Open Checklist Review after login and remove Lightweight mode."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to update. Default: app.py",
    )

    arguments = parser.parse_args()
    app_path = Path(arguments.app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if PATCH_MARKER in source:
        print(f"This patch is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-review-first-remove-lightweight.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(app_path, backup_path)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app_path.parent,
            prefix=f".{app_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated)

        shutil.copymode(app_path, temporary_path)
        temporary_path.replace(app_path)

    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Backup: {backup_path}")
    print("Python syntax and deleted-helper reference validation passed.")
    print("Checklist Review is now the first page after login.")
    print("Checklist Review is the first sidebar menu option.")
    print("Removed Lightweight mode and restored interactive charts.")
    print("Optional weight-chart visibility remains unchanged.")
    print("Restart or redeploy the application to apply the changes.")
    print("Smartphone and login-flow testing are still required.")


if __name__ == "__main__":
    main()
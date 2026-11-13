# scripts/change-button-color.py
#
# Changes only the Checklist Review "Clear All Filters" button:
#   Normal: blue background, white text.
#   Hover:  darker blue.
#   Focus:  visible blue outline.
#
# Leaves Clear History and other buttons unchanged.
# Preserves existing alignment, widget keys, callbacks, and filter behavior.
#
# Run:
#   python scripts/change-button-color.py
#
# Or:
#   python scripts/change-button-color.py app.py
#
# Creates a backup before changing the application.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_CLEAR_ALL_FILTERS_BLUE_BUTTON_V1"
HELPER_NAME = "_review_style_clear_all_filters_button"


HELPER = r'''
# REVIEW_CLEAR_ALL_FILTERS_BLUE_BUTTON_V1
def _review_style_clear_all_filters_button(widget_key):
    import re

    key = str(widget_key)

    # Existing filter widget keys use letters, numbers, underscores,
    # and hyphens. Reject unexpected characters instead of interpolating
    # arbitrary content into CSS.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return

    selector = f'[class~="st-key-{key}"] button'

    css = """
<style>
__SELECTOR__ {
    background-color: #2563eb !important;
    border-color: #2563eb !important;
    color: #ffffff !important;
}
__SELECTOR__ p {
    color: #ffffff !important;
}
__SELECTOR__:hover:not(:disabled) {
    background-color: #1d4ed8 !important;
    border-color: #1d4ed8 !important;
    color: #ffffff !important;
}
__SELECTOR__:active:not(:disabled) {
    background-color: #1e40af !important;
    border-color: #1e40af !important;
}
__SELECTOR__:focus-visible {
    outline: 3px solid #93c5fd !important;
    outline-offset: 2px;
    box-shadow: none !important;
}
__SELECTOR__:disabled {
    opacity: 0.5;
}
</style>
""".replace("__SELECTOR__", selector)

    st.markdown(css, unsafe_allow_html=True)

'''


def find_function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {name} function; found {len(matches)}."
        )

    return matches[0]


def clear_button_key(call):
    if not isinstance(call, ast.Call):
        return None

    # Support both the original button and the existing column wrapper.
    if (
        isinstance(call.func, ast.Name)
        and call.func.id == "_review_filter_control_in_column"
        and len(call.args) >= 3
    ):
        function = call.args[1]
        arguments = call.args[2:]
    else:
        function = call.func
        arguments = call.args

    if not (
        isinstance(function, ast.Attribute)
        and function.attr == "button"
    ):
        return None

    label = arguments[0] if arguments else next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "label"
        ),
        None,
    )

    if not (
        isinstance(label, ast.Constant)
        and isinstance(label.value, str)
        and label.value.strip().casefold() == "clear all filters"
    ):
        return None

    return next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "key"
        ),
        None,
    )


def assigns_owner_id(statement):
    return (
        isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "owner_id"
            for target in statement.targets
        )
    )


def validate_scope(original, updated):
    permitted = {
        "render_checklist_review_page",
        HELPER_NAME,
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the review page and styling helper."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid button-color patch marker.")


def patch_application(source):
    if MARKER in source:
        return source

    tree = ast.parse(source)
    review = find_function(tree, "render_checklist_review_page")

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == HELPER_NAME
        for node in tree.body
    ):
        raise ValueError(
            "The styling helper already exists without its patch marker."
        )

    keys = [
        key
        for node in ast.walk(review)
        if isinstance(node, ast.Call)
        for key in [clear_button_key(node)]
        if key is not None
    ]

    if len(keys) != 1:
        raise ValueError(
            "Could not uniquely identify the keyed Clear All Filters "
            f"button. Found {len(keys)}. Application was not changed."
        )

    key_expression = keys[0]

    # The style is inserted immediately after owner_id is assigned.
    # Only accept key expressions available at that point.
    referenced_names = {
        node.id
        for node in ast.walk(key_expression)
        if isinstance(node, ast.Name)
    }

    if not referenced_names.issubset({
        "owner_id",
        "saved_filter_key",
    }):
        raise ValueError(
            "The button key depends on an unexpected local variable. "
            "Application was not changed."
        )

    for node in ast.walk(key_expression):
        if isinstance(node, ast.Call):
            if not (
                isinstance(node.func, ast.Name)
                and node.func.id == "saved_filter_key"
            ):
                raise ValueError(
                    "Unsupported function in the button key expression."
                )

    owner_positions = [
        index
        for index, statement in enumerate(review.body)
        if assigns_owner_id(statement)
    ]

    if len(owner_positions) != 1:
        raise ValueError(
            "Could not uniquely identify the review owner assignment."
        )

    start_line = min(
        [review.lineno]
        + [
            decorator.lineno
            for decorator in review.decorator_list
        ]
    ) - 1

    end_line = review.end_lineno

    review.body.insert(
        owner_positions[0] + 1,
        ast.Expr(
            value=ast.Call(
                func=ast.Name(
                    id=HELPER_NAME,
                    ctx=ast.Load(),
                ),
                args=[key_expression],
                keywords=[],
            )
        ),
    )

    ast.fix_missing_locations(review)

    replacement = (
        HELPER.strip("\n")
        + "\n\n"
        + ast.unparse(review)
        + "\n\n"
    )

    lines = source.splitlines(keepends=True)
    lines[start_line:end_line] = [replacement]
    updated = "".join(lines)

    compile(updated, "<review-clear-button-color>", "exec")
    validate_scope(source, updated)

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Make the Checklist Review Clear All Filters button blue "
            "without changing Clear History."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to update. Default: app.py",
    )

    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if MARKER in source:
        print(f"The button-color patch is already installed: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-clear-filter-button-color.bak"
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
    print("Python syntax and patch-scope validation passed.")
    print("Clear All Filters now has blue styling with white text.")
    print("Clear History and all other buttons are unchanged.")
    print("Existing layout, widget keys, and callbacks are preserved.")
    print("Restart or redeploy the application, then reload the page.")
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
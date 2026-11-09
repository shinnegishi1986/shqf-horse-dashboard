# scripts/change-view-setting-for-race-checklist.py
#
# Makes both Race Checklist and Checklist Review use wide layout.
# Login, Register, and all other pages remain centered.
#
# Apply after scripts/change-view-setting.py.
#
# Run:
#   python scripts/change-view-setting-for-race-checklist.py
#
# Or specify the application file:
#   python scripts/change-view-setting-for-race-checklist.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# RACE_CHECKLIST_AND_REVIEW_WIDE_LAYOUT_V1"


def find_navigation_key(tree):
    main_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "main"
    ]

    if len(main_functions) != 1:
        raise ValueError("Expected exactly one main() function.")

    navigation_calls = []

    for node in ast.walk(main_functions[0]):
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
            navigation_calls.append(call)

    if len(navigation_calls) != 1:
        raise ValueError(
            "Could not uniquely identify the sidebar page navigation."
        )

    keys = [
        keyword.value
        for keyword in navigation_calls[0].keywords
        if keyword.arg == "key"
    ]

    if not (
        len(keys) == 1
        and isinstance(keys[0], ast.Constant)
        and isinstance(keys[0].value, str)
    ):
        raise ValueError(
            "The navigation widget needs a constant string key. "
            "Apply scripts/change-view-setting.py first."
        )

    return keys[0].value


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)
    navigation_key = find_navigation_key(tree)

    config_statements = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "st"
            and node.value.func.attr == "set_page_config"
        )
    ]

    if len(config_statements) != 1:
        raise ValueError(
            "Expected exactly one top-level st.set_page_config() call."
        )

    statement = config_statements[0]
    call = statement.value

    layout_expression = ast.parse(
        (
            '"wide" if ('
            'st.session_state.get("logged_in", False) and '
            f'st.session_state.get({navigation_key!r}, "Race Checklist") '
            'in ("Race Checklist", "Checklist Review")'
            ') else "centered"'
        ),
        mode="eval",
    ).body

    layout_keywords = [
        keyword
        for keyword in call.keywords
        if keyword.arg == "layout"
    ]

    if len(layout_keywords) > 1:
        raise ValueError("Unexpected duplicate layout arguments.")

    if layout_keywords:
        layout_keywords[0].value = layout_expression
    else:
        call.keywords.append(
            ast.keyword(
                arg="layout",
                value=layout_expression,
            )
        )

    ast.fix_missing_locations(statement)

    lines = source.splitlines(keepends=True)

    lines[statement.lineno - 1:statement.end_lineno] = [
        PATCH_MARKER + "\n" + ast.unparse(statement) + "\n"
    ]

    updated = "".join(lines)

    compile(updated, "<race-checklist-wide-layout>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    def normalize(source):
        tree = ast.parse(source)

        for statement in tree.body:
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and isinstance(statement.value.func.value, ast.Name)
                and statement.value.func.value.id == "st"
                and statement.value.func.attr == "set_page_config"
            ):
                continue

            statement.value.keywords = [
                keyword
                for keyword in statement.value.keywords
                if keyword.arg != "layout"
            ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the page layout setting."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid layout patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Use wide layout for Race Checklist and Checklist Review, "
            "while keeping Login, Register, and other pages centered."
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
        print(f"This layout setting is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-race-checklist-wide-layout.bak"
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
    print("Python syntax and layout-only change validation passed.")
    print("Race Checklist: wide layout.")
    print("Checklist Review: wide layout.")
    print("Login, Register, and all other pages: centered layout.")
    print("Restart or redeploy the application to apply the change.")
    print("Interactive navigation testing is still required.")


if __name__ == "__main__":
    main()
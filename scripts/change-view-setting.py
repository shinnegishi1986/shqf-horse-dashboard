# scripts/change-view-setting.py
#
# Makes Checklist Review use wide layout.
# Login, Register, and all other pages use centered layout.
#
# Run:
#   python scripts/change-view-setting.py
#
# Or specify the application file:
#   python scripts/change-view-setting.py app.py
#
# Uses one st.set_page_config() call.
# The sidebar navigation state determines the layout on each rerun.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# CHECKLIST_REVIEW_ONLY_WIDE_LAYOUT_V1"
NAVIGATION_KEY = "app_navigation_page"


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


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    page_config_statements = [
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

    if len(page_config_statements) != 1:
        raise ValueError(
            "Expected exactly one top-level st.set_page_config() call."
        )

    config_statement = page_config_statements[0]
    config_call = config_statement.value

    main_function = find_function(tree, "main")

    navigation_statements = []

    for node in ast.walk(main_function):
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name) and target.id == "page"
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
            navigation_statements.append(node)

    if len(navigation_statements) != 1:
        raise ValueError(
            "Could not uniquely identify the sidebar page navigation."
        )

    navigation_statement = navigation_statements[0]
    navigation_call = navigation_statement.value

    key_keywords = [
        keyword
        for keyword in navigation_call.keywords
        if keyword.arg == "key"
    ]

    if len(key_keywords) > 1:
        raise ValueError("Unexpected duplicate navigation widget keys.")

    if key_keywords:
        key_value = key_keywords[0].value

        if not (
            isinstance(key_value, ast.Constant)
            and isinstance(key_value.value, str)
        ):
            raise ValueError(
                "The existing navigation key is not a constant string."
            )

        navigation_key = key_value.value
    else:
        navigation_key = NAVIGATION_KEY

        navigation_call.keywords.append(
            ast.keyword(
                arg="key",
                value=ast.Constant(value=navigation_key),
            )
        )

    layout_expression = ast.parse(
        (
            '"wide" if ('
            'st.session_state.get("logged_in", False) and '
            f'st.session_state.get({navigation_key!r}) == "Checklist Review"'
            ') else "centered"'
        ),
        mode="eval",
    ).body

    layout_keywords = [
        keyword
        for keyword in config_call.keywords
        if keyword.arg == "layout"
    ]

    if len(layout_keywords) > 1:
        raise ValueError("Unexpected duplicate layout arguments.")

    if layout_keywords:
        layout_keywords[0].value = layout_expression
    else:
        config_call.keywords.append(
            ast.keyword(
                arg="layout",
                value=layout_expression,
            )
        )

    ast.fix_missing_locations(config_statement)
    ast.fix_missing_locations(navigation_statement)

    lines = source.splitlines(keepends=True)

    edits = [
        (
            config_statement.lineno - 1,
            config_statement.end_lineno,
            PATCH_MARKER + "\n" + ast.unparse(config_statement) + "\n",
        ),
        (
            navigation_statement.lineno - 1,
            navigation_statement.end_lineno,
            (
                " " * navigation_statement.col_offset
                + ast.unparse(navigation_statement)
                + "\n"
            ),
        ),
    ]

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<review-only-wide-layout>", "exec")

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid layout patch marker.")

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Use wide layout only for Checklist Review and centered "
            "layout for Login, Register, and other pages."
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
        print(f"The page-layout setting is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-view-setting-change.bak"
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
    print("Python syntax validation passed.")
    print("Checklist Review: wide layout.")
    print("Login and Register: centered layout.")
    print("All other pages: centered layout.")
    print("Restart or redeploy the application to apply the change.")
    print("Interactive navigation testing is still required.")


if __name__ == "__main__":
    main()
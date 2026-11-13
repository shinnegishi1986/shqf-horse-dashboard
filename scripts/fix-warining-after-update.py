# scripts/fix-warining-after-update.py
#
# Fixes:
#   The widget with key "saved_filter_2_page_size_selector"
#   was created with a default value but also had its value
#   set via the Session State API.
#
# Run:
#   python scripts/fix-warining-after-update.py
#
# Or specify the application file:
#   python scripts/fix-warining-after-update.py app.py
#
# Behavior:
#   - Uses the restored page-size selection when Session State contains it.
#   - Preserves the original widget default when no stored value exists.
#   - Does not clear filters or change records.
#   - Does not disable Streamlit warnings globally.
#
# Creates a backup before changing the application.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_PAGE_SIZE_DEFAULT_STATE_FIX_V1"
HELPER_NAME = "_review_page_size_without_duplicate_default"


HELPER = r'''
# REVIEW_PAGE_SIZE_DEFAULT_STATE_FIX_V1
def _review_page_size_without_duplicate_default(
    widget_function,
    *args,
    **kwargs,
):
    key = kwargs.get("key")

    if key is not None and key in st.session_state:
        # index=None supplies no competing default. Streamlit uses the
        # existing Session State value associated with this widget key.
        if len(args) >= 3:
            positional = list(args)
            positional[2] = None
            args = tuple(positional)
            kwargs.pop("index", None)
        else:
            kwargs["index"] = None

    return widget_function(*args, **kwargs)

'''


def source_offset(lines, line_number, byte_column):
    line = lines[line_number - 1]

    character_column = len(
        line.encode("utf-8")[:byte_column].decode("utf-8")
    )

    return (
        sum(len(item) for item in lines[:line_number - 1])
        + character_column
    )


def identifies_page_size_key(expression):
    # Handles both:
    #   saved_filter_key(owner_id, "page_size_selector")
    #   f"saved_filter_{owner_id}_page_size_selector"
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (
            node.value == "page_size_selector"
            or node.value.endswith("_page_size_selector")
        )
        for node in ast.walk(expression)
    )


def patch_application(source):
    if MARKER in source:
        return source, 0

    tree = ast.parse(source)

    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == HELPER_NAME
        for node in tree.body
    ):
        raise ValueError(
            "The helper name already exists without the expected marker."
        )

    lines = source.splitlines(keepends=True)
    edits = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "selectbox"
        ):
            continue

        key_keyword = next(
            (
                keyword
                for keyword in node.keywords
                if keyword.arg == "key"
            ),
            None,
        )

        if (
            key_keyword is None
            or not identifies_page_size_key(key_keyword.value)
        ):
            continue

        # The application uses keyword keys for page-size selectors.
        # Reject unexpected positional parameters rather than guessing.
        if len(node.args) > 3:
            raise ValueError(
                "A page-size selector has more than three positional "
                f"arguments at line {node.lineno}. "
                "The application was not changed."
            )

        start = source_offset(
            lines,
            node.func.lineno,
            node.func.col_offset,
        )

        function_end = source_offset(
            lines,
            node.func.end_lineno,
            node.func.end_col_offset,
        )

        call_end = source_offset(
            lines,
            node.end_lineno,
            node.end_col_offset,
        )

        original_function = source[start:function_end]

        # Preserve the original call arguments and formatting.
        # Example:
        #   st.selectbox(...)
        # becomes:
        #   helper(st.selectbox, ...)
        opening_parenthesis = function_end

        while (
            opening_parenthesis < call_end
            and source[opening_parenthesis].isspace()
        ):
            opening_parenthesis += 1

        if source[opening_parenthesis] != "(":
            raise ValueError(
                f"Unexpected selectbox syntax at line {node.lineno}."
            )

        original_arguments = source[
            opening_parenthesis + 1:call_end - 1
        ]

        replacement = (
            f"{HELPER_NAME}("
            f"{original_function}, "
            f"{original_arguments})"
        )

        edits.append((start, call_end, replacement))

    if not edits:
        raise ValueError(
            "Could not find a selectbox with a page_size_selector key. "
            "The application was not changed. The current app.py is "
            "needed to identify a differently structured selector."
        )

    ordered = sorted(edits, key=lambda item: item[0])

    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Overlapping page-size selector edits detected.")

    updated = source

    for start, end, replacement in reversed(ordered):
        updated = updated[:start] + replacement + updated[end:]

    # Insert before the first top-level function or class. This preserves
    # module docstrings, future imports, and the existing import section.
    updated_tree = ast.parse(updated)

    definitions = [
        node
        for node in updated_tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
    ]

    if not definitions:
        raise ValueError("Could not locate a safe helper insertion point.")

    first_definition = definitions[0]

    insertion_line = min(
        [first_definition.lineno]
        + [
            decorator.lineno
            for decorator in first_definition.decorator_list
        ]
    )

    updated_lines = updated.splitlines(keepends=True)

    updated_lines.insert(
        insertion_line - 1,
        HELPER.strip("\n") + "\n\n",
    )

    updated = "".join(updated_lines)

    compile(updated, "<review-page-size-state-fix>", "exec")

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid patch marker.")

    return updated, len(edits)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Remove conflicting page-size widget defaults after "
            "Checklist Review filter-state restoration."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to patch. Default: app.py",
    )

    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if MARKER in source:
        print(f"The page-size warning fix is already installed: {app_path}")
        return

    try:
        updated, count = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-page-size-warning-fix.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename the backup before applying this patch."
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
    print(f"Patched page-size selector calls: {count}")
    print("Python syntax validation passed.")
    print("Restored page-size state now takes precedence over defaults.")
    print("Filters, database records, and horse weights are unchanged.")
    print("Restart or redeploy the app, then reload Checklist Review.")
    print(
        "Test by changing page size, updating a horse, and confirming "
        "the page size remains selected without the warning."
    )
    print("Interactive Streamlit testing has not been performed.")


if __name__ == "__main__":
    main()
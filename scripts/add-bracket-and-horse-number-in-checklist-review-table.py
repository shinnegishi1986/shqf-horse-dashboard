# scripts/add-bracket-and-horse-number-in-checklist-review-table.py
#
# Adds adjacent columns to the Checklist Review results table:
#
#   Bracket Number | Horse Number | Horse | Memo (if installed)
#
# Preserves existing columns, including Memo and Race Class.
#
# Does not change:
#   - Database records or schema
#   - Filter conditions or saved filters
#   - Horse weights
#   - Race templates
#   - Blog features
#
# Existing Bracket Number / Horse Number columns are repositioned
# rather than duplicated.
#
# Creates a timestamped source backup before replacing app.py.
#
# Stop Streamlit before running:
#
#   python scripts/add-bracket-and-horse-number-in-checklist-review-table.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


FUNCTION_NAME = "build_summary_dataframe"

COLUMN_NAMES = {
    "Bracket Number",
    "Horse Number",
}


def patch_source(source):
    tree = ast.parse(source)

    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == FUNCTION_NAME
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {FUNCTION_NAME} function; "
            f"found {len(matches)}."
        )

    function = matches[0]

    row_dictionaries = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Dict)
        and {"ID", "Horse", "Race"}.issubset(
            {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant)
            }
        )
    ]

    if len(row_dictionaries) != 1:
        raise ValueError(
            "Cannot uniquely identify the checklist "
            "summary row dictionary."
        )

    row = row_dictionaries[0]

    original_row = ast.dump(
        row,
        include_attributes=False,
    )

    has_entry_loop = any(
        isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "entry"
        for node in ast.walk(function)
    )

    if not has_entry_loop:
        raise ValueError(
            "Unexpected summary structure: checklist rows "
            "do not use the expected 'entry' variable."
        )

    # Remove existing copies of these two columns so they can
    # be placed together without introducing duplicates.
    pairs = [
        (key, value)
        for key, value in zip(row.keys, row.values)
        if not (
            isinstance(key, ast.Constant)
            and key.value in COLUMN_NAMES
        )
    ]

    labels = [
        key.value
        if isinstance(key, ast.Constant)
        else None
        for key, value in pairs
    ]

    position = labels.index("Horse")

    # Keep numeric values numeric. Missing values remain None.
    pairs[position:position] = [
        (
            ast.Constant(value="Bracket Number"),
            ast.parse(
                "entry.get('bracket_number')",
                mode="eval",
            ).body,
        ),
        (
            ast.Constant(value="Horse Number"),
            ast.parse(
                "entry.get('horse_number')",
                mode="eval",
            ).body,
        ),
    ]

    row.keys = [
        key for key, value in pairs
    ]

    row.values = [
        value for key, value in pairs
    ]

    if (
        ast.dump(row, include_attributes=False)
        == original_row
    ):
        return source, False

    ast.fix_missing_locations(function)

    start_line = min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1

    lines = source.splitlines(keepends=True)

    lines[start_line:function.end_lineno] = [
        ast.unparse(function) + "\n\n"
    ]

    updated = "".join(lines)

    # Compile without running the Streamlit application.
    compile(
        updated,
        "<review-bracket-horse-number-patch>",
        "exec",
    )

    def outside_summary_function(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == FUNCTION_NAME
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if (
        outside_summary_function(source)
        != outside_summary_function(updated)
    ):
        raise ValueError(
            "Unexpected changes outside the summary function. "
            "Application was not changed."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add adjacent Bracket Number and Horse Number "
            "columns to the Checklist Review results table."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application source file. Default: app.py",
    )

    arguments = parser.parse_args()
    app_path = Path(arguments.app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    original_bytes = app_path.read_bytes()

    try:
        source = original_bytes.decode("utf-8-sig")

        updated, changed = patch_source(source)

    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "Bracket Number and Horse Number are already "
            "adjacent, in the requested order, before Horse. "
            "No changes were made."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup_path = app_path.with_name(
        f"{app_path.name}."
        f"before-bracket-horse-table-{timestamp}.bak"
    )

    temporary_path = None

    try:
        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed during validation. "
                "Run the patch again."
            )

        shutil.copy2(app_path, backup_path)

        if backup_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app_path.parent,
            prefix=f".{app_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            temporary_file.write(updated)

        shutil.copymode(
            app_path,
            temporary_path,
        )

        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed before replacement. "
                "Run the patch again."
            )

        temporary_path.replace(app_path)
        temporary_path = None

    except Exception as error:
        raise SystemExit(
            "Patch could not be completed.\n"
            f"{error}"
        ) from error

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Source backup: {backup_path}")
    print("Python syntax and change-scope validation passed.")
    print(
        "Column order: Bracket Number | Horse Number | Horse"
    )
    print(
        "Existing Memo, Race Class, and other columns "
        "were preserved."
    )
    print(
        "Database records, weights, and filters "
        "were not changed."
    )
    print(
        "Restart Streamlit and open Checklist Review."
    )


if __name__ == "__main__":
    main()
# scripts/add-memo-in-table.py
#
# Adds a Memo column after Horse in the Checklist Review results table.
#
# Does not change:
#   - Memo keyword matching
#   - Filter state or saved filters
#   - Database records or schema
#   - Horse weights
#   - Race templates or blog features
#
# Creates an app.py backup before applying the patch.
# Safe to run again: an existing Memo column is detected.
#
# Run:
#   python scripts/add-memo-in-table.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_MATCHED_TABLE_MEMO_V1"
FUNCTION_NAME = "build_summary_dataframe"


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
            "Cannot uniquely identify the checklist summary "
            "row dictionary. Application was not changed."
        )

    row = row_dictionaries[0]

    labels = [
        key.value if isinstance(key, ast.Constant) else None
        for key in row.keys
    ]

    if "Memo" in labels:
        return source, False

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

    # Keep the memo near the horse name for easy comparison.
    position = labels.index("Horse") + 1

    row.keys.insert(
        position,
        ast.Constant(value="Memo"),
    )

    # Preserve multiline/Unicode text and display missing memos as blank.
    # Only the display value is converted; stored records are unchanged.
    row.values.insert(
        position,
        ast.parse(
            "'' if entry.get('memo') is None "
            "else str(entry.get('memo'))",
            mode="eval",
        ).body,
    )

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
        MARKER
        + "\n"
        + ast.unparse(function)
        + "\n\n"
    ]

    updated = "".join(lines)

    # Validate the entire application without executing it.
    compile(
        updated,
        "<checklist-review-memo-patch>",
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
            "Add Memo to the Checklist Review matched-results table."
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
            "The summary table already contains a Memo column. "
            "No changes were made."
        )
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    backup_path = app_path.with_name(
        f"{app_path.name}.before-memo-table-{timestamp}.bak"
    )

    temporary_path = None

    try:
        # Do not overwrite source changed after validation.
        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed during validation. "
                "Run the patch again."
            )

        shutil.copy2(app_path, backup_path)

        if backup_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Backup verification failed."
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
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated)

        shutil.copymode(app_path, temporary_path)

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
    print("Added Memo immediately after Horse in the results table.")
    print("Missing memos display as blank.")
    print("Multiline and Unicode memo text is preserved.")
    print("Database records and filtering logic were not changed.")
    print("Restart Streamlit to display the new column.")


if __name__ == "__main__":
    main()
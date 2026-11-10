# scripts/fix-filter-issue.py_
#
# Fixes:
#   1. Mixed numeric/text types in the Checklist Review summary dataframe.
#   2. Deprecated use_container_width arguments.
#
# Run:
#   python scripts/fix-filter-issue.py_ app.py
#
# The .py_ filename is intentional, matching the requested filename.
#
# Scope:
#   - Changes summary-table serialization only.
#   - Converts numeric display columns to nullable numeric types.
#   - Converts missing numeric display values to null, not empty strings.
#   - Keeps text display columns consistently typed.
#   - Replaces use_container_width with width.
#
# Does NOT:
#   - Change database records or horse weights.
#   - Filter out records with missing weights.
#   - Reset filters or filter history.
#   - Change chart calculations or login state.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# REVIEW_ARROW_TYPES_AND_WIDTH_FIX_V1"
HELPER_NAME = "_review_arrow_safe_summary"


HELPER = r'''
# REVIEW_ARROW_TYPES_AND_WIDTH_FIX_V1
def _review_arrow_safe_summary(dataframe):
    # This function receives a newly created display dataframe.
    # It does not modify the underlying checklist records.
    if dataframe.empty:
        return dataframe

    numeric_columns = {
        "ID",
        "Days Since Last Race",
        "Distance",
        "Previous Distance",
        "Weight Change (kg)",
        "Horse Weight (kg)",
        "Odds",
        "Program Number",
        "Number of Horses",
        "Bracket Number",
        "Horse Number",
    }

    for column in dataframe.columns:
        if column in numeric_columns:
            numeric = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

            # Keep non-finite values out of numeric display columns.
            numeric = numeric.mask(
                numeric.isin([float("inf"), float("-inf")])
            )

            if column == "ID":
                valid = numeric.dropna()

                if valid.empty or (valid % 1 == 0).all():
                    dataframe[column] = numeric.astype("Int64")
                else:
                    dataframe[column] = numeric.astype("Float64")
            else:
                dataframe[column] = numeric.astype("Float64")

        else:
            # Finishing positions remain text so nonnumeric race outcomes
            # are preserved. Currency-formatted prize text also stays text.
            dataframe[column] = (
                dataframe[column]
                .astype("string")
                .fillna("")
            )

    return dataframe

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


def source_offset(lines, line_number, byte_column):
    # AST column positions are UTF-8 byte offsets.
    line = lines[line_number - 1]

    character_column = len(
        line.encode("utf-8")[:byte_column].decode("utf-8")
    )

    return (
        sum(len(item) for item in lines[:line_number - 1])
        + character_column
    )


def node_span(lines, node):
    return (
        source_offset(
            lines,
            node.lineno,
            node.col_offset,
        ),
        source_offset(
            lines,
            node.end_lineno,
            node.end_col_offset,
        ),
    )


def is_pandas_dataframe_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pd"
        and node.func.attr == "DataFrame"
    )


def patch_application(source):
    if PATCH_MARKER in source:
        return source, 0

    tree = ast.parse(source)

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == HELPER_NAME
        for node in tree.body
    ):
        raise ValueError(
            "The Arrow-safe summary helper already exists without "
            "the expected patch marker."
        )

    summary = find_function(tree, "build_summary_dataframe")

    if summary.decorator_list:
        raise ValueError(
            "Unexpected decorators on build_summary_dataframe."
        )

    # Identify the original display-dataframe return without replacing
    # the rest of the summary-building function.
    returns = [
        node
        for node in ast.walk(summary)
        if isinstance(node, ast.Return)
        and is_pandas_dataframe_call(node.value)
    ]

    if len(returns) != 1:
        raise ValueError(
            "Could not uniquely identify the summary dataframe return. "
            "Expected return pd.DataFrame(...)."
        )

    lines = source.splitlines(keepends=True)
    edits = []

    dataframe_call = returns[0].value
    start, end = node_span(lines, dataframe_call)

    original_expression = source[start:end]

    edits.append(
        (
            start,
            end,
            f"{HELPER_NAME}({original_expression})",
        )
    )

    # Add the helper before the summary builder.
    helper_position = source_offset(
        lines,
        summary.lineno,
        0,
    )

    edits.append(
        (
            helper_position,
            helper_position,
            HELPER.strip("\n") + "\n\n",
        )
    )

    width_updates = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        old_keywords = [
            keyword
            for keyword in node.keywords
            if keyword.arg == "use_container_width"
        ]

        if not old_keywords:
            continue

        if len(old_keywords) != 1:
            raise ValueError(
                "Unexpected duplicate use_container_width arguments."
            )

        if any(
            keyword.arg == "width"
            for keyword in node.keywords
        ):
            raise ValueError(
                "A call contains both width and use_container_width. "
                f"Review the call at line {node.lineno}."
            )

        keyword = old_keywords[0]
        value = keyword.value

        if (
            isinstance(value, ast.Constant)
            and type(value.value) is bool
        ):
            replacement = (
                "width='stretch'"
                if value.value
                else "width='content'"
            )
        else:
            value_start, value_end = node_span(lines, value)
            expression = source[value_start:value_end]

            replacement = (
                "width=("
                f"'stretch' if ({expression}) else 'content'"
                ")"
            )

        keyword_start, keyword_end = node_span(lines, keyword)

        edits.append(
            (
                keyword_start,
                keyword_end,
                replacement,
            )
        )

        width_updates += 1

    # Reject overlapping edits rather than risk corrupting the application.
    spans = sorted(
        (start, end)
        for start, end, _ in edits
        if start != end
    )

    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            raise ValueError(
                "Overlapping edits were detected. "
                "The application was not changed."
            )

    updated = source

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        updated = (
            updated[:start]
            + replacement
            + updated[end:]
        )

    compile(updated, "<review-arrow-and-width-fix>", "exec")
    validate_patch(updated)

    return updated, width_updates


def validate_patch(updated):
    tree = ast.parse(updated)

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid serialization-fix patch marker.")

    find_function(tree, HELPER_NAME)
    summary = find_function(tree, "build_summary_dataframe")

    wrapped_returns = [
        node
        for node in ast.walk(summary)
        if (
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == HELPER_NAME
        )
    ]

    if len(wrapped_returns) != 1:
        raise ValueError(
            "The summary dataframe was not wrapped correctly."
        )

    remaining_old_keywords = [
        keyword
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "use_container_width"
    ]

    if remaining_old_keywords:
        raise ValueError(
            "Deprecated use_container_width arguments remain."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fix Checklist Review dataframe serialization "
            "and deprecated container-width arguments."
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
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    source = app_path.read_text(
        encoding="utf-8-sig"
    )

    if PATCH_MARKER in source:
        print(
            f"The serialization and width fix is already applied to: "
            f"{app_path}"
        )
        return

    try:
        updated, width_updates = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-arrow-and-width-fix.bak"
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
            temporary_path = Path(
                temporary_file.name
            )
            temporary_file.write(updated)

        shutil.copymode(
            app_path,
            temporary_path,
        )

        temporary_path.replace(app_path)

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Backup: {backup_path}")
    print("Python syntax and patch-structure validation passed.")
    print("Summary numeric columns now use nullable numeric types.")
    print("Missing horse weights remain missing, not empty-string numbers.")
    print(
        f"Updated {width_updates} deprecated container-width argument(s)."
    )
    print("Database records and active filter conditions were not changed.")
    print("Restart or redeploy the application, then reload Checklist Review.")
    print(
        "Verify that valid-weight and missing-weight records both display "
        "without Arrow serialization warnings."
    )
    print(
        "If results are still unexpectedly restricted, that requires "
        "separate inspection of the current filtering code."
    )


if __name__ == "__main__":
    main()
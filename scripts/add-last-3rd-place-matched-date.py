# scripts/add-last-3rd-place-matched-date.py
#
# Inserts Latest Top-3 Matched Date directly into Review Summary.
# Compatible with the supplied application's review structure. [1]
#
# Run against the application file that Streamlit actually launches:
#
#   python scripts/add-last-3rd-place-matched-date.py app.py
#
# If Streamlit launches a different file, specify that file instead.
#
# This script:
#   - Works whether the earlier recency patch was applied or not.
#   - Removes earlier recency rendering calls to avoid duplicate metrics.
#   - Uses actual filtered records, before pagination.
#   - Includes finishing positions 1, 2, and 3.
#   - Adds no database queries or sample data.
#   - Preserves existing filters, charts, and other review metrics.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# REVIEW_SUMMARY_TOP_THREE_RECENCY_V3"

OLD_RENDER_FUNCTIONS = {
    "render_latest_third_place_matched_date",
    "render_latest_top_three_matched_date",
}


SUMMARY_BLOCK = '''
    # REVIEW_SUMMARY_TOP_THREE_RECENCY_V3
    def _summary_latest_top_three_date(entries):
        latest_date = None

        for entry in entries:
            finished_place = clean_text(entry.get("finished_place"))

            if not finished_place.isdecimal():
                continue

            if int(finished_place) not in (1, 2, 3):
                continue

            race_date = parse_race_date(entry.get("date_of_race"))

            if race_date is None:
                continue

            if latest_date is None or race_date > latest_date:
                latest_date = race_date

        return latest_date

    def _summary_render_top_three_recency(entries, scope):
        from datetime import date as _recency_date

        today = _recency_date.today()
        latest_date = _summary_latest_top_three_date(entries)

        latest_date_column, latest_age_column = st.columns(2)

        with latest_date_column:
            st.metric(
                label=f"{scope}: Latest Top-3 Matched Date",
                value=(
                    latest_date.isoformat()
                    if latest_date is not None
                    else "N/A"
                ),
            )

        with latest_age_column:
            if latest_date is None:
                age_text = "N/A"
            else:
                days_since = (today - latest_date).days
                age_text = (
                    f"{days_since:,} day(s)"
                    if days_since >= 0
                    else "Future date"
                )

            st.metric(
                label=f"{scope}: Days Since Latest Top-3 Match",
                value=age_text,
            )

        if latest_date is None:
            st.caption(
                f"{scope}: No matching first-, second-, or third-place "
                "finish has a valid race date."
            )
        elif latest_date > today:
            st.warning(
                f"{scope}: The latest top-three result is dated in "
                "the future. Check its race date or finishing position."
            )

    _summary_render_top_three_recency(
        first_filtered_checklists,
        "First Filter",
    )

    if second_filter_enabled:
        _summary_render_top_three_recency(
            (
                second_filtered_checklists
                if second_filtered_checklists is not None
                else []
            ),
            "Second Filter",
        )

    st.caption(
        "Top-3 means finishing position 1, 2, or 3. "
        "The latest matched date uses all actual filtered results, "
        "before pagination. Days since the latest match uses the "
        "application server's current date. "
        "This indicates recency, not a reliability score."
    )

'''


def find_review_function(tree):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "render_checklist_review_page"
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one render_checklist_review_page function."
        )

    return matches[0]


def is_summary_heading(statement):
    if not isinstance(statement, ast.Expr):
        return False

    call = statement.value

    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "subheader"
        and bool(call.args)
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "Review Summary"
    )


def is_old_recency_call(statement):
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id in OLD_RENDER_FUNCTIONS
    )


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)
    review = find_review_function(tree)

    headings = [
        statement
        for statement in review.body
        if is_summary_heading(statement)
    ]

    if len(headings) != 1:
        raise ValueError(
            "Could not uniquely locate st.subheader('Review Summary'). "
            "The application was not changed."
        )

    existing_functions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    for required in ("clean_text", "parse_race_date"):
        if required not in existing_functions:
            raise ValueError(
                f"Required application helper is missing: {required}"
            )

    edits = []

    # Remove previous rendering calls, but leave their helper definitions
    # untouched so unrelated application code is preserved.
    for statement in review.body:
        if is_old_recency_call(statement):
            edits.append(
                (
                    statement.lineno - 1,
                    statement.end_lineno,
                    "",
                )
            )

    # Insert directly after the visible Review Summary heading.
    heading = headings[0]

    edits.append(
        (
            heading.end_lineno,
            heading.end_lineno,
            SUMMARY_BLOCK,
        )
    )

    lines = source.splitlines(keepends=True)

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement] if replacement else []

    updated = "".join(lines)

    compile(updated, "<review-summary-recency-fix>", "exec")
    validate_patch(source, updated)

    return updated


def validate_patch(original, updated):
    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("The new patch marker is invalid.")

    tree = ast.parse(updated)
    review = find_review_function(tree)

    if any(is_old_recency_call(node) for node in review.body):
        raise ValueError("An obsolete recency rendering call remains.")

    heading_index = next(
        index
        for index, node in enumerate(review.body)
        if is_summary_heading(node)
    )

    next_statement = review.body[heading_index + 1]

    if not (
        isinstance(next_statement, ast.FunctionDef)
        and next_statement.name == "_summary_latest_top_three_date"
    ):
        raise ValueError(
            "The new metrics were not inserted directly into Review Summary."
        )

    # Compare the application AST after removing only the intended changes.
    block_nodes = ast.parse(
        "def _temporary_review():\n" + SUMMARY_BLOCK
    ).body[0].body

    def normalize(source, remove_new_block=False):
        parsed = ast.parse(source)
        function = find_review_function(parsed)

        function.body = [
            node
            for node in function.body
            if not is_old_recency_call(node)
        ]

        if remove_new_block:
            index = next(
                index
                for index, node in enumerate(function.body)
                if is_summary_heading(node)
            )

            actual = function.body[
                index + 1:index + 1 + len(block_nodes)
            ]

            if [
                ast.dump(node, include_attributes=False)
                for node in actual
            ] != [
                ast.dump(node, include_attributes=False)
                for node in block_nodes
            ]:
                raise ValueError("The inserted metrics block is invalid.")

            del function.body[index + 1:index + 1 + len(block_nodes)]

        return ast.dump(parsed, include_attributes=False)

    if normalize(original) != normalize(updated, remove_new_block=True):
        raise ValueError(
            "Unexpected changes outside the Review Summary recency display."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Display Latest Top-3 Matched Date directly in Review Summary."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="The Python file Streamlit launches. Default: app.py",
    )

    args = parser.parse_args()
    app_path = Path(args.app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if PATCH_MARKER in source:
        print(f"This fix is already present in: {app_path}")
        print(
            "If the metrics are still missing, verify that Streamlit "
            "launches this file and restart or redeploy the application."
        )
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-summary-top-three-recency-v3.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before applying this fix."
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
    print("Latest Top-3 Matched Date is now directly inside Review Summary.")
    print("Finishing positions 1, 2, and 3 are included.")
    print("Only actual filtered results are used.")
    print(
        "Restart or redeploy the Streamlit app that launches this file, "
        "then reload Checklist Review."
    )
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
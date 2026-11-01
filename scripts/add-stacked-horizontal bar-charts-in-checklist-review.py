# scripts/add-stacked-horizontal bar-charts-in-checklist-review.py
#
# Adds Venue Count and Jockey Count stacked horizontal charts to Checklist Review.
# Based on the supplied application. [1]
#
# Run from the project root:
#   python "scripts/add-stacked-horizontal bar-charts-in-checklist-review.py"
#
# Or specify the application file:
#   python "scripts/add-stacked-horizontal bar-charts-in-checklist-review.py" app.py
#
# Each chart has one horizontal stacked bar:
#   - Largest individual category starts at the left.
#   - Remaining individual categories follow in descending count order.
#   - Categories outside the top 20 are combined into "Other" at the far right.
#   - Tooltips show counts and percentage shares.
#
# The charts use first-filter results by default. When the second filter is
# enabled, a checkbox lets you switch to its results.
#
# Performance:
#   - Uses records already loaded by Checklist Review; no database queries.
#   - Counts venues and jockeys together in one pass.
#   - Sends at most 21 aggregated rows per chart to the browser.
#   - No additional charting package is imported.
#
# Existing optional weight-change filter changes are preserved.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# CHECKLIST_REVIEW_STACKED_COUNT_CHARTS_V1"

CHART_HELPERS = r'''
# CHECKLIST_REVIEW_STACKED_COUNT_CHARTS_V1
def _review_count_chart_rows(counts, labels, total, top_limit=20):
    import heapq

    if total <= 0:
        return []

    ranked = heapq.nsmallest(
        top_limit,
        counts.items(),
        key=lambda item: (
            -item[1],
            labels[item[0]].casefold(),
            repr(item[0]),
        ),
    )

    rows = []
    shown_count = 0

    for order, (category_key, count) in enumerate(ranked):
        label = labels[category_key]

        # Unique legend keys keep identically named entities separate.
        legend_key = f"{order + 1}. {label}"

        rows.append(
            {
                "bar": "Share of selected records",
                "category": label,
                "legend_key": legend_key,
                "count": count,
                "share": count / total,
                "order": order,
            }
        )
        shown_count += count

    remainder = total - shown_count

    if remainder > 0:
        rows.append(
            {
                "bar": "Share of selected records",
                "category": "Other (remaining categories)",
                "legend_key": "Other (remaining categories)",
                "count": remainder,
                "share": remainder / total,
                "order": len(rows),
            }
        )

    return rows


def _render_review_stacked_count_chart(title, rows, total, category_count):
    st.markdown(f"### {title}")

    if not rows:
        st.info("No matching records to chart.")
        return

    largest = rows[0]

    st.caption(
        f"{total:,} checklist record(s) across {category_count:,} categories. "
        f"Largest: {largest['category']} — "
        f"{largest['count']:,} ({largest['share']:.1%})."
    )

    domain = [row["legend_key"] for row in rows]

    palette = [
        "#2563EB", "#F97316", "#10B981", "#EF4444", "#8B5CF6",
        "#06B6D4", "#D97706", "#DB2777", "#65A30D", "#4F46E5",
        "#0D9488", "#DC2626", "#9333EA", "#0284C7", "#CA8A04",
        "#BE185D", "#16A34A", "#7C3AED", "#0891B2", "#EA580C",
    ]

    colors = [
        "#9CA3AF"
        if row["category"] == "Other (remaining categories)"
        else palette[index % len(palette)]
        for index, row in enumerate(rows)
    ]

    spec = {
        "height": 85,
        "mark": {
            "type": "bar",
            "size": 42,
        },
        "encoding": {
            "x": {
                "field": "count",
                "type": "quantitative",
                "stack": "zero",
                "scale": {
                    "domain": [0, total],
                    "nice": False,
                },
                "axis": {
                    "title": "Checklist record count",
                    "format": ",.0f",
                    "tickMinStep": 1,
                    "grid": False,
                },
            },
            "y": {
                "field": "bar",
                "type": "nominal",
                "axis": None,
            },
            "color": {
                "field": "legend_key",
                "type": "nominal",
                "scale": {
                    "domain": domain,
                    "range": colors,
                },
                "legend": {
                    "title": None,
                    "orient": "bottom",
                    "direction": "horizontal",
                    "columns": 2,
                    "labelLimit": 250,
                    "symbolType": "square",
                },
            },
            "order": {
                "field": "order",
                "type": "quantitative",
                "sort": "ascending",
            },
            "tooltip": [
                {
                    "field": "category",
                    "type": "nominal",
                    "title": "Category",
                },
                {
                    "field": "count",
                    "type": "quantitative",
                    "title": "Record count",
                    "format": ",.0f",
                },
                {
                    "field": "share",
                    "type": "quantitative",
                    "title": "Share",
                    "format": ".1%",
                },
            ],
        },
        "config": {
            "view": {"stroke": None},
        },
    }

    st.vega_lite_chart(
        pd.DataFrame(rows),
        spec=spec,
        use_container_width=True,
    )


def render_review_stacked_count_charts(
    owner_id,
    first_filtered_checklists,
    second_filtered_checklists=None,
    second_filter_enabled=False,
):
    from collections import Counter

    st.subheader("Venue and Jockey Dominance")

    show_charts = st.checkbox(
        "Show venue and jockey count charts",
        value=True,
        key=f"review_stacked_count_charts_visible_{owner_id}",
    )

    if not show_charts:
        return

    use_second_filter = False

    if second_filter_enabled:
        use_second_filter = st.checkbox(
            "Use second-filter results for these charts",
            value=False,
            key=f"review_stacked_count_charts_second_filter_{owner_id}",
        )

    if use_second_filter:
        records = (
            second_filtered_checklists
            if second_filtered_checklists is not None
            else []
        )
        scope = "Second-filter results"
    else:
        records = first_filtered_checklists
        scope = "First-filter results"

    st.caption(
        f"Scope: {scope}, before pagination. "
        "Each checklist contributes one venue count and one jockey count. "
        "These charts show record concentration, not win rates. "
        "Largest individual category is at the left; "
        "smaller categories follow. Any combined Other segment is last."
    )

    total = len(records)

    if total == 0:
        st.info("No matching checklist records for the selected chart scope.")
        return

    venue_counts = Counter()
    jockey_counts = Counter()
    venue_labels = {}
    jockey_labels = {}

    for entry in records:
        venue_id = entry.get("venue_id")
        venue_name = clean_text(entry.get("venue_name"))

        if venue_id is not None:
            venue_key = ("id", venue_id)
            venue_label = venue_name or f"Venue #{venue_id}"
        elif venue_name and venue_name != "No venue selected":
            venue_key = ("name", venue_name)
            venue_label = venue_name
        else:
            venue_key = ("missing",)
            venue_label = "(No venue selected)"

        venue_counts[venue_key] += 1
        venue_labels[venue_key] = venue_label

        jockey_id = entry.get("jockey_id")
        jockey_name = clean_text(entry.get("jockey_name"))

        if jockey_id is not None:
            jockey_key = ("id", jockey_id)
            jockey_label = jockey_name or f"Jockey #{jockey_id}"
        elif jockey_name and jockey_name != "No jockey selected":
            jockey_key = ("name", jockey_name)
            jockey_label = jockey_name
        else:
            jockey_key = ("missing",)
            jockey_label = "(No jockey selected)"

        jockey_counts[jockey_key] += 1
        jockey_labels[jockey_key] = jockey_label

    venue_rows = _review_count_chart_rows(
        venue_counts,
        venue_labels,
        total,
    )

    jockey_rows = _review_count_chart_rows(
        jockey_counts,
        jockey_labels,
        total,
    )

    _render_review_stacked_count_chart(
        "Venue Count",
        venue_rows,
        total,
        len(venue_counts),
    )

    _render_review_stacked_count_chart(
        "Jockey Count",
        jockey_rows,
        total,
        len(jockey_counts),
    )

'''

CHART_CALL = '''
    render_review_stacked_count_charts(
        owner_id=owner_id,
        first_filtered_checklists=first_filtered_checklists,
        second_filtered_checklists=second_filtered_checklists,
        second_filter_enabled=second_filter_enabled,
    )

'''


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    review_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "render_checklist_review_page"
    ]

    if len(review_functions) != 1:
        raise ValueError(
            "Expected exactly one render_checklist_review_page function."
        )

    review = review_functions[0]
    lines = source.splitlines(keepends=True)

    anchor = (
        "    review_metrics = "
        "calculate_review_metrics(first_filtered_checklists)"
    )

    anchor_positions = [
        index
        for index in range(review.lineno - 1, review.end_lineno)
        if lines[index].rstrip("\r\n") == anchor
    ]

    if len(anchor_positions) != 1:
        raise ValueError(
            "Could not uniquely locate the Review Summary insertion point. "
            "The application was not changed."
        )

    call_position = anchor_positions[0]
    lines.insert(call_position, CHART_CALL)

    # Insert helpers before the review function so they are defined before main.
    lines.insert(review.lineno - 1, CHART_HELPERS + "\n")

    updated = "".join(lines)
    ast.parse(updated)

    return updated


def validate_aggregation(source):
    from collections import Counter

    tree = ast.parse(source)

    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_review_count_chart_rows"
    )

    namespace = {}

    exec(
        compile(
            ast.Module(body=[function], type_ignores=[]),
            "<stacked-count-chart-tests>",
            "exec",
        ),
        namespace,
    )

    aggregate = namespace["_review_count_chart_rows"]

    counts = Counter({"A": 2, "B": 8, "C": 4})
    labels = {key: key for key in counts}
    rows = aggregate(counts, labels, 14)

    assert [row["category"] for row in rows] == ["B", "C", "A"]
    assert [row["count"] for row in rows] == [8, 4, 2]
    assert abs(sum(row["share"] for row in rows) - 1.0) < 1e-12

    counts = Counter({f"Category {index}": index + 1 for index in range(100)})
    labels = {key: key for key in counts}
    total = sum(counts.values())
    rows = aggregate(counts, labels, total)

    assert len(rows) == 21
    assert rows[0]["count"] == 100
    assert rows[-1]["category"] == "Other (remaining categories)"
    assert sum(row["count"] for row in rows) == total

    assert aggregate(Counter(), {}, 0) == []


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add lightweight stacked horizontal venue and jockey count "
            "charts to Checklist Review."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to update. Default: app.py",
    )

    arguments = parser.parse_args()
    app_path = Path(arguments.app_file)

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if PATCH_MARKER in source:
        print("The stacked horizontal chart patch is already applied.")
        return

    try:
        updated = patch_application(source)
        validate_aggregation(updated)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-stacked-count-charts.bak"
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
    print(f"Original application backup: {backup_path}")
    print("Python syntax and chart aggregation validation passed.")
    print("Added Venue Count and Jockey Count stacked horizontal charts.")
    print("Largest individual category appears at the left.")
    print("Existing application changes were preserved.")


if __name__ == "__main__":
    main()
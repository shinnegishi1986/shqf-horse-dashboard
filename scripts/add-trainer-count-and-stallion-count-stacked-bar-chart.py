# scripts/add-trainer-count-and-stallion-count-stacked-bar-chart.py
#
# Adds Trainer Count and Stallion Count stacked horizontal charts
# to the existing Checklist Review dominance charts.
#
# Run from the project root:
#   python scripts/add-trainer-count-and-stallion-count-stacked-bar-chart.py
#
# Or specify the application file:
#   python scripts/add-trainer-count-and-stallion-count-stacked-bar-chart.py app.py
#
# Preserves:
#   - Existing venue and jockey charts.
#   - Largest individual category on the left.
#   - Top-20 categories plus an optional Other segment.
#   - First-filter / second-filter chart scope.
#   - Apple-device tap tooltips.
#   - Dark-panel text contrast fixes.
#   - Existing optional weight-change filtering.
#
# Performance:
#   - Counts all four entity types in the existing single pass.
#   - Does not add database queries.
#   - Reuses the existing aggregated chart renderer.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# TRAINER_STALLION_STACKED_COUNT_CHARTS_V1"


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

    # Require the existing chart infrastructure.
    find_function(tree, "_review_count_chart_rows")
    find_function(tree, "_render_review_stacked_count_chart")

    chart_function = find_function(
        tree,
        "render_review_stacked_count_charts",
    )

    if chart_function.decorator_list:
        raise ValueError(
            "Unexpected decorators on render_review_stacked_count_charts. "
            "No changes were applied."
        )

    lines = source.splitlines(keepends=True)

    function_source = "".join(
        lines[chart_function.lineno - 1:chart_function.end_lineno]
    )

    patched = function_source

    def replace_once(old, new):
        nonlocal patched

        count = patched.count(old)

        if count != 1:
            raise ValueError(
                "Cannot safely apply this patch. "
                f"Expected one occurrence, found {count}:\n{old}"
            )

        patched = patched.replace(old, new, 1)

    replace_once(
        '    st.subheader("Venue and Jockey Dominance")',
        '    st.subheader("Venue, Jockey, Trainer and Stallion Dominance")',
    )

    replace_once(
        '        "Show venue and jockey count charts",',
        '        "Show venue, jockey, trainer and stallion count charts",',
    )

    replace_once(
        '        "Each checklist contributes one venue count and one jockey count. "',
        '        "Each checklist contributes one count to each chart: "\n'
        '        "venue, jockey, trainer and stallion. "\n'
        '        "Missing selections are included as separate categories. "',
    )

    replace_once(
        "    venue_counts = Counter()\n"
        "    jockey_counts = Counter()\n"
        "    venue_labels = {}\n"
        "    jockey_labels = {}",
        "    venue_counts = Counter()\n"
        "    jockey_counts = Counter()\n"
        "    trainer_counts = Counter()\n"
        "    stallion_counts = Counter()\n"
        "    venue_labels = {}\n"
        "    jockey_labels = {}\n"
        "    trainer_labels = {}\n"
        "    stallion_labels = {}",
    )

    # Extend the existing records loop, rather than iterating records again.
    replace_once(
        "        jockey_counts[jockey_key] += 1\n"
        "        jockey_labels[jockey_key] = jockey_label",
        '''        jockey_counts[jockey_key] += 1
        jockey_labels[jockey_key] = jockey_label

        trainer_id = entry.get("trainer_id")
        trainer_name = clean_text(entry.get("trainer_name"))

        if trainer_id is not None:
            trainer_key = ("id", trainer_id)
            trainer_label = trainer_name or f"Trainer #{trainer_id}"
        elif trainer_name and trainer_name != "No trainer selected":
            trainer_key = ("name", trainer_name)
            trainer_label = trainer_name
        else:
            trainer_key = ("missing",)
            trainer_label = "(No trainer selected)"

        trainer_counts[trainer_key] += 1
        trainer_labels[trainer_key] = trainer_label

        # Use the stallion field, not broodmare_sire_id.
        stallion_id = entry.get("stallion_id")
        stallion_name = clean_text(entry.get("stallion_name"))

        if stallion_id is not None:
            stallion_key = ("id", stallion_id)
            stallion_label = stallion_name or f"Stallion #{stallion_id}"
        elif stallion_name and stallion_name != "No stallion selected":
            stallion_key = ("name", stallion_name)
            stallion_label = stallion_name
        else:
            stallion_key = ("missing",)
            stallion_label = "(No stallion selected)"

        stallion_counts[stallion_key] += 1
        stallion_labels[stallion_key] = stallion_label''',
    )

    replace_once(
        '''    jockey_rows = _review_count_chart_rows(
        jockey_counts,
        jockey_labels,
        total,
    )''',
        '''    jockey_rows = _review_count_chart_rows(
        jockey_counts,
        jockey_labels,
        total,
    )

    trainer_rows = _review_count_chart_rows(
        trainer_counts,
        trainer_labels,
        total,
    )

    stallion_rows = _review_count_chart_rows(
        stallion_counts,
        stallion_labels,
        total,
    )''',
    )

    replace_once(
        '''    _render_review_stacked_count_chart(
        "Jockey Count",
        jockey_rows,
        total,
        len(jockey_counts),
    )''',
        '''    _render_review_stacked_count_chart(
        "Jockey Count",
        jockey_rows,
        total,
        len(jockey_counts),
    )

    _render_review_stacked_count_chart(
        "Trainer Count",
        trainer_rows,
        total,
        len(trainer_counts),
    )

    _render_review_stacked_count_chart(
        "Stallion Count",
        stallion_rows,
        total,
        len(stallion_counts),
    )''',
    )

    updated = (
        "".join(lines[:chart_function.lineno - 1])
        + PATCH_MARKER
        + "\n"
        + patched
        + "".join(lines[chart_function.end_lineno:])
    )

    compile(updated, "<trainer-stallion-chart-patch>", "exec")
    validate_unchanged_functions(source, updated)
    validate_chart_logic(updated)

    return updated


def validate_unchanged_functions(original, updated):
    target = "render_review_stacked_count_charts"

    def remaining_ast(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == target
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if remaining_ast(original) != remaining_ast(updated):
        raise ValueError(
            "Unexpected changes outside the chart orchestration function."
        )


def validate_chart_logic(source):
    from collections import Counter

    tree = ast.parse(source)

    aggregate_function = find_function(
        tree,
        "_review_count_chart_rows",
    )

    chart_function = find_function(
        tree,
        "render_review_stacked_count_charts",
    )

    class StreamlitStub:
        def __init__(self, use_second=False, visible=True):
            self.use_second = use_second
            self.visible = visible

        def subheader(self, *args, **kwargs):
            pass

        def caption(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def checkbox(self, label, value=False, **kwargs):
            if label == "Use second-filter results for these charts":
                return self.use_second
            return self.visible

    rendered = []

    def capture_chart(title, rows, total, category_count):
        rendered.append(
            {
                "title": title,
                "rows": rows,
                "total": total,
                "category_count": category_count,
            }
        )

    namespace = {
        "st": StreamlitStub(),
        "clean_text": lambda value: (
            "" if value is None else str(value).strip()
        ),
        "_render_review_stacked_count_chart": capture_chart,
    }

    module = ast.Module(
        body=[aggregate_function, chart_function],
        type_ignores=[],
    )

    exec(
        compile(module, "<chart-logic-validation>", "exec"),
        namespace,
    )

    render = namespace["render_review_stacked_count_charts"]

    records = [
        {
            "trainer_id": 1,
            "trainer_name": "Trainer A",
            "stallion_id": 10,
            "stallion_name": "Stallion A",
        },
        {
            "trainer_id": 1,
            "trainer_name": "Trainer A",
            "stallion_id": 11,
            "stallion_name": "Stallion B",
        },
        {
            "trainer_id": 2,
            "trainer_name": "Trainer B",
            "stallion_id": 10,
            "stallion_name": "Stallion A",
        },
        {},
    ]

    render(
        owner_id=1,
        first_filtered_checklists=records,
    )

    expected_titles = [
        "Venue Count",
        "Jockey Count",
        "Trainer Count",
        "Stallion Count",
    ]

    if [chart["title"] for chart in rendered] != expected_titles:
        raise AssertionError("Expected all four charts in the correct order.")

    for chart in rendered:
        if sum(row["count"] for row in chart["rows"]) != len(records):
            raise AssertionError(
                f"Count mismatch in {chart['title']}."
            )

    by_title = {chart["title"]: chart for chart in rendered}

    trainer_rows = by_title["Trainer Count"]["rows"]
    stallion_rows = by_title["Stallion Count"]["rows"]

    if (
        trainer_rows[0]["category"] != "Trainer A"
        or trainer_rows[0]["count"] != 2
    ):
        raise AssertionError("Trainer dominance ordering is incorrect.")

    if (
        stallion_rows[0]["category"] != "Stallion A"
        or stallion_rows[0]["count"] != 2
    ):
        raise AssertionError("Stallion dominance ordering is incorrect.")

    if not any(
        row["category"] == "(No trainer selected)"
        for row in trainer_rows
    ):
        raise AssertionError("Missing trainer category was not retained.")

    if not any(
        row["category"] == "(No stallion selected)"
        for row in stallion_rows
    ):
        raise AssertionError("Missing stallion category was not retained.")

    # Verify that all charts use the selected second-filter scope.
    rendered.clear()
    namespace["st"] = StreamlitStub(use_second=True)

    render(
        owner_id=1,
        first_filtered_checklists=records,
        second_filtered_checklists=records[:1],
        second_filter_enabled=True,
    )

    if len(rendered) != 4 or any(
        chart["total"] != 1
        for chart in rendered
    ):
        raise AssertionError("Second-filter chart scope is incorrect.")

    # Verify that disabling chart visibility skips chart rendering.
    rendered.clear()
    namespace["st"] = StreamlitStub(visible=False)

    render(
        owner_id=1,
        first_filtered_checklists=records,
    )

    if rendered:
        raise AssertionError("Hidden charts should not be rendered.")

    # Verify that large category counts remain bounded by aggregation.
    counts = Counter(
        {("id", index): index + 1 for index in range(100)}
    )
    labels = {
        key: f"Trainer {key[1]}"
        for key in counts
    }

    aggregated = namespace["_review_count_chart_rows"](
        counts,
        labels,
        sum(counts.values()),
    )

    if len(aggregated) > 21:
        raise AssertionError("Chart aggregation exceeded the row limit.")

    if sum(row["count"] for row in aggregated) != sum(counts.values()):
        raise AssertionError("Aggregated chart counts were not preserved.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add Trainer Count and Stallion Count stacked horizontal "
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
        print("Trainer and stallion stacked charts are already installed.")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-trainer-stallion-charts.bak"
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
    print("Python syntax and chart-logic validation passed.")
    print("Added Trainer Count and Stallion Count stacked bar charts.")
    print("All four category counts use the existing records loop.")
    print("Existing tooltip and text-contrast renderer was preserved.")
    print("Reload the application to view the charts.")
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
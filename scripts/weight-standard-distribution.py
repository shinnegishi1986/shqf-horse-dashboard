# scripts/weight-standard-distribution.py
#
# Adds an optional horse-weight distribution chart to Checklist Review.
#
# Run:
#   python scripts/weight-standard-distribution.py
#
# Or specify the application file:
#   python scripts/weight-standard-distribution.py app.py
#
# Chart:
#   - Uses horse_weight (horse body weight in kg), not weight_change.
#   - Hidden by default.
#   - Uses actual filtered results before pagination.
#   - Offers second-filter results when the second filter is enabled.
#   - Shows a histogram, mean, and mean +/- one sample standard deviation.
#   - Does not assume that weights follow a normal distribution.
#
# Performance:
#   - No additional database queries.
#   - No weight aggregation or chart rendering while hidden.
#   - Sends at most 24 histogram bins and 3 reference lines to the browser.
#
# Responsive layout:
#   - Container-width chart.
#   - Compact chart height and two-column metric rows.
#   - Explicit high-contrast chart colors.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# OPTIONAL_WEIGHT_STANDARD_DISTRIBUTION_V1"


HELPERS = r'''
# OPTIONAL_WEIGHT_STANDARD_DISTRIBUTION_V1
def render_review_weight_standard_distribution(
    owner_id,
    first_filtered_checklists,
    second_filtered_checklists=None,
    second_filter_enabled=False,
):
    show_chart = st.checkbox(
        "Show horse-weight distribution and standard deviation",
        value=False,
        key=f"review_weight_standard_distribution_visible_{owner_id}",
    )

    if not show_chart:
        return

    import math
    import statistics

    use_second = False

    if second_filter_enabled:
        use_second = st.checkbox(
            "Use second-filter results for the weight chart",
            value=False,
            key=f"review_weight_standard_distribution_second_{owner_id}",
        )

    if use_second:
        records = (
            second_filtered_checklists
            if second_filtered_checklists is not None
            else []
        )
        scope = "Second Filter"
    else:
        records = first_filtered_checklists
        scope = "First Filter"

    weights = []
    excluded = 0

    for entry in records:
        value = entry.get("horse_weight")

        if value is None or isinstance(value, bool):
            excluded += 1
            continue

        try:
            weight = float(value)
        except (TypeError, ValueError, OverflowError):
            excluded += 1
            continue

        if not math.isfinite(weight) or weight <= 0:
            excluded += 1
            continue

        weights.append(weight)

    st.markdown("### Horse-Weight Distribution")

    count = len(weights)

    st.caption(
        f"{scope} · {count:,} valid weight record(s) · "
        f"{excluded:,} missing or invalid weight(s) excluded. "
        "Uses all matching checklist records before pagination."
    )

    if not weights:
        st.info("No valid horse weights are available for these filters.")
        return

    mean_weight = statistics.mean(weights)
    standard_deviation = (
        statistics.stdev(weights)
        if count >= 2
        else None
    )

    first_column, second_column = st.columns(2)

    first_column.metric(
        "Mean Horse Weight",
        f"{mean_weight:,.1f} kg",
    )

    second_column.metric(
        "Standard Deviation",
        (
            f"{standard_deviation:,.1f} kg"
            if standard_deviation is not None
            else "N/A"
        ),
    )

    minimum = min(weights)
    maximum = max(weights)

    minimum_column, maximum_column = st.columns(2)

    minimum_column.metric("Minimum Weight", f"{minimum:,.1f} kg")
    maximum_column.metric("Maximum Weight", f"{maximum:,.1f} kg")

    if standard_deviation is None:
        st.caption(
            "At least two valid weight records are required "
            "to calculate sample standard deviation."
        )

    if minimum == maximum:
        bin_count = 1
        lower_bound = max(0.0, minimum - 0.5)
        upper_bound = maximum + 0.5
    else:
        bin_count = min(24, max(5, math.ceil(math.sqrt(count))))
        lower_bound = minimum
        upper_bound = maximum

    bin_width = (upper_bound - lower_bound) / bin_count
    bin_counts = [0] * bin_count

    for weight in weights:
        index = int((weight - lower_bound) / bin_width)
        index = max(0, min(bin_count - 1, index))
        bin_counts[index] += 1

    bins = [
        {
            "from_weight": lower_bound + index * bin_width,
            "to_weight": (
                upper_bound
                if index == bin_count - 1
                else lower_bound + (index + 1) * bin_width
            ),
            "count": bin_counts[index],
        }
        for index in range(bin_count)
    ]

    reference_lines = [
        {
            "weight": mean_weight,
            "reference": "Mean",
        }
    ]

    if standard_deviation is not None and standard_deviation > 0:
        reference_lines.extend(
            [
                {
                    "weight": mean_weight - standard_deviation,
                    "reference": "Mean - 1 SD",
                },
                {
                    "weight": mean_weight + standard_deviation,
                    "reference": "Mean + 1 SD",
                },
            ]
        )

    # Include the reference lines even when they extend beyond observed weights.
    domain_minimum = min(
        lower_bound,
        *(line["weight"] for line in reference_lines),
    )
    domain_maximum = max(
        upper_bound,
        *(line["weight"] for line in reference_lines),
    )

    padding = max(0.5, (domain_maximum - domain_minimum) * 0.04)

    x_scale = {
        "domain": [
            domain_minimum - padding,
            domain_maximum + padding,
        ],
        "nice": False,
    }

    spec = {
        "height": 240,
        "background": "#111827",
        "padding": 10,
        "layer": [
            {
                "mark": {
                    "type": "bar",
                    "color": "#60A5FA",
                    "opacity": 0.85,
                },
                "encoding": {
                    "x": {
                        "field": "from_weight",
                        "type": "quantitative",
                        "bin": "binned",
                        "scale": x_scale,
                        "axis": {
                            "title": "Horse weight (kg)",
                            "tickCount": 4,
                            "format": ".0f",
                        },
                    },
                    "x2": {
                        "field": "to_weight",
                    },
                    "y": {
                        "field": "count",
                        "type": "quantitative",
                        "axis": {
                            "title": "Record count",
                            "tickCount": 4,
                            "tickMinStep": 1,
                            "format": ",.0f",
                        },
                    },
                    "tooltip": [
                        {
                            "field": "from_weight",
                            "type": "quantitative",
                            "title": "From (kg)",
                            "format": ".1f",
                        },
                        {
                            "field": "to_weight",
                            "type": "quantitative",
                            "title": "To (kg)",
                            "format": ".1f",
                        },
                        {
                            "field": "count",
                            "type": "quantitative",
                            "title": "Records",
                            "format": ",.0f",
                        },
                    ],
                },
            },
            {
                "data": {
                    "values": reference_lines,
                },
                "mark": {
                    "type": "rule",
                    "strokeWidth": 2,
                },
                "encoding": {
                    "x": {
                        "field": "weight",
                        "type": "quantitative",
                        "scale": x_scale,
                    },
                    "color": {
                        "field": "reference",
                        "type": "nominal",
                        "scale": {
                            "domain": [
                                "Mean",
                                "Mean - 1 SD",
                                "Mean + 1 SD",
                            ],
                            "range": [
                                "#FBBF24",
                                "#F472B6",
                                "#34D399",
                            ],
                        },
                        "legend": {
                            "title": None,
                            "orient": "bottom",
                            "direction": "horizontal",
                            "columns": 1,
                            "labelColor": "#F8FAFC",
                        },
                    },
                    "tooltip": [
                        {
                            "field": "reference",
                            "type": "nominal",
                            "title": "Reference",
                        },
                        {
                            "field": "weight",
                            "type": "quantitative",
                            "title": "Weight (kg)",
                            "format": ".1f",
                        },
                    ],
                },
            },
        ],
        "config": {
            "view": {
                "stroke": None,
            },
            "axis": {
                "labelColor": "#F8FAFC",
                "titleColor": "#F8FAFC",
                "domainColor": "#64748B",
                "tickColor": "#64748B",
                "gridColor": "#334155",
                "labelFontSize": 11,
                "titleFontSize": 12,
            },
            "legend": {
                "labelColor": "#F8FAFC",
                "titleColor": "#F8FAFC",
                "labelFontSize": 11,
            },
        },
    }

    st.vega_lite_chart(
        pd.DataFrame(bins),
        spec=spec,
        use_container_width=True,
    )

    if standard_deviation is not None:
        st.caption(
            f"Mean ± 1 sample SD: "
            f"{mean_weight - standard_deviation:,.1f} to "
            f"{mean_weight + standard_deviation:,.1f} kg. "
            "Each checklist is one observation, so a horse can appear "
            "more than once. The chart does not assume a normal distribution."
        )

'''


RENDER_CALL = '''
    render_review_weight_standard_distribution(
        owner_id=owner_id,
        first_filtered_checklists=first_filtered_checklists,
        second_filtered_checklists=second_filtered_checklists,
        second_filter_enabled=second_filter_enabled,
    )

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


def is_metrics_assignment(statement):
    return (
        isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "review_metrics"
            for target in statement.targets
        )
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "calculate_review_metrics"
    )


def is_chart_call(statement):
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id
        == "render_review_weight_standard_distribution"
    )


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)
    review = find_function(tree, "render_checklist_review_page")

    if review.decorator_list:
        raise ValueError(
            "Unexpected decorators on render_checklist_review_page."
        )

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == "render_review_weight_standard_distribution"
        for node in tree.body
    ):
        raise ValueError(
            "The weight chart helper already exists without the expected "
            "patch marker."
        )

    anchors = [
        statement
        for statement in review.body
        if is_metrics_assignment(statement)
    ]

    if len(anchors) != 1:
        raise ValueError(
            "Could not uniquely locate the review metrics assignment."
        )

    lines = source.splitlines(keepends=True)

    lines.insert(anchors[0].lineno - 1, RENDER_CALL)
    lines.insert(review.lineno - 1, HELPERS + "\n")

    updated = "".join(lines)

    compile(updated, "<weight-standard-distribution>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    helper_name = "render_review_weight_standard_distribution"

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == helper_name
            )
        ]

        review = find_function(tree, "render_checklist_review_page")

        review.body = [
            statement
            for statement in review.body
            if not is_chart_call(statement)
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the optional weight chart."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid weight-chart patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add an optional responsive horse-weight histogram "
            "with mean and sample standard deviation."
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
        print(f"The optional weight chart is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-standard-distribution.bak"
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
    print("Added an optional horse-weight distribution chart.")
    print("The chart is hidden by default.")
    print("Uses actual filtered horse weights, not weight changes.")
    print("Restart or redeploy the application to view the change.")
    print("Tablet, smartphone, and desktop visual testing is still required.")


if __name__ == "__main__":
    main()
# scripts/fix-bar-charts-tooltip-in-apple-device.py
#
# Updates the stacked venue/jockey chart renderer added by:
#   scripts/add-stacked-horizontal bar-charts-in-checklist-review.py
#
# Run:
#   python scripts/fix-bar-charts-tooltip-in-apple-device.py
#
# Or specify the application file:
#   python scripts/fix-bar-charts-tooltip-in-apple-device.py app.py
#
# Behavior:
#   - Tap a stacked segment to show a persistent tooltip bubble.
#   - Tap another segment to update the bubble.
#   - Tap outside a segment or press Escape to dismiss.
#   - Mouse hover continues to show tooltips.
#   - Keyboard focus also shows tooltips.
#
# Uses existing aggregated chart data. No extra database queries,
# external JavaScript libraries, or CDN requests.
# Preserves the rest of the application and previous filter changes.
# Original application context: [1]

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# APPLE_TOUCH_STACKED_CHART_TOOLTIP_V1"


REPLACEMENT_RENDERER = r'''
# APPLE_TOUCH_STACKED_CHART_TOOLTIP_V1
def _render_review_stacked_count_chart(title, rows, total, category_count):
    import json
    import math
    import streamlit.components.v1 as components

    st.markdown(f"### {title}")

    if not rows or total <= 0:
        st.info("No matching records to chart.")
        return

    largest = rows[0]

    st.caption(
        f"{total:,} checklist record(s) across {category_count:,} categories. "
        f"Largest: {largest['category']} — "
        f"{largest['count']:,} ({largest['share']:.1%})."
    )

    palette = [
        "#2563EB", "#F97316", "#10B981", "#EF4444", "#8B5CF6",
        "#06B6D4", "#D97706", "#DB2777", "#65A30D", "#4F46E5",
        "#0D9488", "#DC2626", "#9333EA", "#0284C7", "#CA8A04",
        "#BE185D", "#16A34A", "#7C3AED", "#0891B2", "#EA580C",
    ]

    chart_rows = []

    for index, row in enumerate(rows):
        count = float(row["count"])

        if not math.isfinite(count) or count <= 0:
            continue

        category = str(row["category"])

        chart_rows.append(
            {
                "category": category,
                "count": count,
                "share": count / total,
                "color": (
                    "#9CA3AF"
                    if category == "Other (remaining categories)"
                    else palette[index % len(palette)]
                ),
            }
        )

    if not chart_rows:
        st.info("No valid chart counts.")
        return

    payload = json.dumps(
        {
            "title": str(title),
            "total": int(total),
            "rows": chart_rows,
        },
        ensure_ascii=True,
        allow_nan=False,
    )

    # Prevent data values from terminating the embedded script element.
    payload = (
        payload.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    template = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    :root {
        color-scheme: light dark;
        --foreground: #172033;
        --background: #ffffff;
        --border: #d1d5db;
        --muted: #64748b;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --foreground: #f1f5f9;
            --background: #172033;
            --border: #64748b;
            --muted: #cbd5e1;
        }
    }

    * { box-sizing: border-box; }

    body {
        margin: 0;
        padding: 8px 6px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 13px;
        color: var(--foreground);
        background: transparent;
    }

    .hint {
        margin: 0 0 12px;
        color: var(--muted);
        font-size: 12px;
    }

    .bar {
        display: flex;
        width: 100%;
        height: 48px;
        overflow: hidden;
        border-radius: 6px;
        background: #e5e7eb;
    }

    .segment {
        display: block;
        flex-shrink: 0;
        min-width: 0;
        height: 100%;
        margin: 0;
        padding: 0;
        border: 0;
        border-radius: 0;
        appearance: none;
        -webkit-appearance: none;
        -webkit-tap-highlight-color: transparent;
        touch-action: manipulation;
        cursor: pointer;
    }

    .segment:hover,
    .segment:focus-visible,
    .segment.selected {
        box-shadow: inset 0 0 0 3px var(--foreground);
        outline: none;
    }

    .axis {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        margin-top: 7px;
        color: var(--muted);
        font-size: 11px;
    }

    .legend {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 6px 12px;
        margin-top: 16px;
        max-height: 190px;
        overflow-y: auto;
        overscroll-behavior: contain;
        padding: 3px;
    }

    .legend-item {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;
        padding: 5px;
        border: 0;
        border-radius: 4px;
        font: inherit;
        color: inherit;
        background: transparent;
        text-align: left;
        cursor: pointer;
        touch-action: manipulation;
    }

    .legend-item:focus-visible {
        outline: 2px solid var(--foreground);
        outline-offset: -2px;
    }

    .swatch {
        width: 11px;
        height: 11px;
        flex: 0 0 11px;
        border-radius: 2px;
    }

    .legend-label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 12px;
    }

    #tooltip {
        position: fixed;
        z-index: 1000;
        max-width: min(300px, calc(100vw - 16px));
        padding: 11px 13px;
        border: 1px solid var(--border);
        border-radius: 11px;
        color: var(--foreground);
        background: var(--background);
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.24);
        pointer-events: none;
        overflow-wrap: anywhere;
        font-size: 13px;
        line-height: 1.5;
    }

    #tooltip[hidden] { display: none; }

    .tooltip-title {
        font-weight: 700;
        margin-bottom: 3px;
    }

    .tooltip-note {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
    }
</style>
</head>
<body>
<p class="hint">
    Tap a segment or legend item for details. Tap outside to dismiss.
</p>

<div id="bar" class="bar" role="group"></div>

<div class="axis" aria-hidden="true">
    <span>0</span>
    <span>Checklist record count</span>
    <span id="total"></span>
</div>

<div id="legend" class="legend" role="group" aria-label="Chart categories"></div>

<div id="tooltip" role="tooltip" hidden>
    <div id="tooltip-title" class="tooltip-title"></div>
    <div id="tooltip-count"></div>
    <div id="tooltip-share"></div>
    <div class="tooltip-note">Tap outside to close</div>
</div>

<script>
"use strict";

const chart = __CHART_DATA__;
const bar = document.getElementById("bar");
const legend = document.getElementById("legend");
const tooltip = document.getElementById("tooltip");
const segments = [];
const numberFormat = new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 0
});
const percentFormat = new Intl.NumberFormat(undefined, {
    style: "percent",
    maximumFractionDigits: 1
});

let pinned = false;
let activeIndex = null;
let anchorElement = null;

bar.setAttribute("aria-label", chart.title);
document.getElementById("total").textContent = numberFormat.format(chart.total);

function positionTooltip(element) {
    const rect = element.getBoundingClientRect();

    tooltip.style.left = "8px";
    tooltip.style.top = "8px";

    const width = tooltip.offsetWidth;
    const height = tooltip.offsetHeight;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;

    const center = rect.left + rect.width / 2;
    const left = Math.max(
        8,
        Math.min(center - width / 2, viewportWidth - width - 8)
    );

    let top = rect.bottom + 10;

    if (top + height > viewportHeight - 8) {
        top = rect.top - height - 10;
    }

    top = Math.max(8, Math.min(top, viewportHeight - height - 8));

    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
}

function showTooltip(index, element) {
    const row = chart.rows[index];

    if (activeIndex !== null) {
        segments[activeIndex].classList.remove("selected");
    }

    activeIndex = index;
    anchorElement = element;
    segments[index].classList.add("selected");

    document.getElementById("tooltip-title").textContent = row.category;
    document.getElementById("tooltip-count").textContent =
        "Record count: " + numberFormat.format(row.count);
    document.getElementById("tooltip-share").textContent =
        "Share: " + percentFormat.format(row.share);

    tooltip.hidden = false;
    positionTooltip(element);
}

function hideTooltip() {
    if (activeIndex !== null) {
        segments[activeIndex].classList.remove("selected");
    }

    tooltip.hidden = true;
    activeIndex = null;
    anchorElement = null;
    pinned = false;
}

function bindInteractions(element, index) {
    element.dataset.chartIndex = String(index);
    element.setAttribute("aria-describedby", "tooltip");

    // Click is the common activation path for touch, mouse, and keyboard.
    // No preventDefault on touchstart, so vertical page scrolling remains usable.
    element.addEventListener("click", function(event) {
        event.stopPropagation();
        pinned = true;
        showTooltip(index, element);
    });

    element.addEventListener("pointerenter", function(event) {
        if (event.pointerType === "mouse" && !pinned) {
            showTooltip(index, element);
        }
    });

    element.addEventListener("pointerleave", function(event) {
        if (event.pointerType === "mouse" && !pinned) {
            hideTooltip();
        }
    });

    element.addEventListener("focus", function() {
        if (!pinned) {
            showTooltip(index, element);
        }
    });

    element.addEventListener("blur", function() {
        if (!pinned) {
            hideTooltip();
        }
    });
}

chart.rows.forEach(function(row, index) {
    const label =
        row.category + ": " +
        numberFormat.format(row.count) + " records, " +
        percentFormat.format(row.share);

    const segment = document.createElement("button");
    segment.type = "button";
    segment.className = "segment";
    segment.style.width = (row.share * 100) + "%";
    segment.style.backgroundColor = row.color;
    segment.setAttribute("aria-label", label);

    segments.push(segment);
    bindInteractions(segment, index);
    bar.appendChild(segment);

    // Legend buttons also expose very narrow segments to touch users.
    const legendItem = document.createElement("button");
    legendItem.type = "button";
    legendItem.className = "legend-item";
    legendItem.setAttribute("aria-label", label);

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.backgroundColor = row.color;
    swatch.setAttribute("aria-hidden", "true");

    const legendLabel = document.createElement("span");
    legendLabel.className = "legend-label";
    legendLabel.textContent =
        row.category + " (" + numberFormat.format(row.count) + ")";

    legendItem.appendChild(swatch);
    legendItem.appendChild(legendLabel);
    bindInteractions(legendItem, index);
    legend.appendChild(legendItem);
});

document.addEventListener("click", function(event) {
    if (!event.target.closest("[data-chart-index]")) {
        hideTooltip();
    }
});

document.addEventListener("keydown", function(event) {
    if (event.key === "Escape") {
        hideTooltip();
    }
});

window.addEventListener("resize", function() {
    if (!tooltip.hidden && anchorElement) {
        positionTooltip(anchorElement);
    }
});

document.addEventListener("scroll", function() {
    if (!tooltip.hidden && anchorElement) {
        positionTooltip(anchorElement);
    }
}, true);
</script>
</body>
</html>
"""

    components.html(
        template.replace("__CHART_DATA__", payload),
        height=355,
        scrolling=False,
    )
'''


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    renderers = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_review_stacked_count_chart"
    ]

    if len(renderers) != 1:
        raise ValueError(
            "Expected exactly one _render_review_stacked_count_chart "
            "function. Apply the stacked horizontal chart patch first."
        )

    renderer = renderers[0]

    if renderer.decorator_list:
        raise ValueError(
            "The chart renderer has unexpected decorators. "
            "The application was not changed."
        )

    lines = source.splitlines(keepends=True)

    updated = (
        "".join(lines[:renderer.lineno - 1])
        + REPLACEMENT_RENDERER.strip("\n")
        + "\n\n"
        + "".join(lines[renderer.end_lineno:])
    )

    ast.parse(updated)

    return updated


def validate_patch(original, updated):
    original_tree = ast.parse(original)
    updated_tree = ast.parse(updated)

    target_name = "_render_review_stacked_count_chart"

    def without_renderer(tree):
        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == target_name
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if without_renderer(original_tree) != without_renderer(updated_tree):
        raise ValueError(
            "Unexpected changes outside the chart renderer were detected."
        )

    compile(updated, "<patched-application>", "exec")

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("The tooltip patch marker is invalid.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add tap-activated tooltip bubbles to the Checklist Review "
            "stacked horizontal charts."
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
        print("The Apple-device tooltip patch is already applied.")
        return

    try:
        updated = patch_application(source)
        validate_patch(source, updated)
    except Exception as error:
        raise SystemExit(
            f"Patch validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-apple-tooltip-fix.bak"
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
    print(f"Original application backup: {backup_path}")
    print("Python syntax and renderer-only change validation passed.")
    print("Tap a chart segment or legend item to display its tooltip bubble.")
    print("Physical iPad/Safari testing is still required.")


if __name__ == "__main__":
    main()
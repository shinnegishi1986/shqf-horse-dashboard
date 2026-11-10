# scripts/fix-weight-chart-tooltip-for-smart-device.py
#
# Adds tap-activated range tooltips to the horse-weight histogram.
#
# Run:
#   python scripts/fix-weight-chart-tooltip-for-smart-device.py
#
# Or specify the application file:
#   python scripts/fix-weight-chart-tooltip-for-smart-device.py app.py
#
# Preserves:
#   - Fixed 5 kg bins.
#   - Top-three finishers only.
#   - Weight range of 350–650 kg inclusive.
#   - Mean and sample standard deviation calculations.
#   - Optional chart visibility.
#   - First-filter / second-filter scope.
#   - Lightweight mode, when installed.
#
# Interaction:
#   - Tap a bar to show its range and record count.
#   - Tap another bar to change the tooltip.
#   - Tap outside the bars to dismiss.
#   - Mouse hover and keyboard focus also show details.
#   - A range selector makes narrow and empty bins accessible.
#
# No external JavaScript libraries or CDN requests.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# TOUCH_WEIGHT_HISTOGRAM_TOOLTIPS_V1"
TARGET_FUNCTION = "render_review_weight_standard_distribution"


HELPER = r'''
# TOUCH_WEIGHT_HISTOGRAM_TOOLTIPS_V1
def _render_touch_weight_histogram(data, spec=None, **kwargs):
    import json
    import streamlit.components.v1 as components

    # Keep the existing older-device text fallback.
    lightweight_check = globals().get("_older_device_lightweight_enabled")
    lightweight_renderer = globals().get("_older_device_vega_lite_chart")

    if (
        callable(lightweight_check)
        and lightweight_check()
        and callable(lightweight_renderer)
    ):
        return lightweight_renderer(data, spec=spec, **kwargs)

    bins = [
        {
            "lower": float(lower),
            "upper": float(upper),
            "count": int(count),
        }
        for lower, upper, count in data[
            ["from_weight", "to_weight", "count"]
        ].itertuples(index=False, name=None)
    ]

    references = []

    for layer in (spec or {}).get("layer", []):
        values = layer.get("data", {}).get("values", [])

        for value in values:
            if "weight" in value and "reference" in value:
                references.append(
                    {
                        "weight": float(value["weight"]),
                        "label": str(value["reference"]),
                    }
                )

    payload = json.dumps(
        {
            "bins": bins,
            "references": references,
        },
        ensure_ascii=True,
        allow_nan=False,
    )

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
* { box-sizing: border-box; }
html, body {
    margin: 0;
    background: #111827;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color-scheme: dark;
}
body { padding: 10px; }
.hint {
    font-size: 12px;
    color: #cbd5e1;
    margin: 0 0 8px;
}
svg {
    display: block;
    width: 100%;
    height: 235px;
    overflow: visible;
}
.hit {
    cursor: pointer;
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
}
.hit:focus { outline: none; }
.highlight { stroke: #ffffff; stroke-width: 2; }
.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 14px;
    font-size: 12px;
    margin: 4px 0 10px;
}
label { display: block; font-size: 12px; margin-bottom: 5px; }
select {
    width: 100%;
    min-height: 42px;
    padding: 8px;
    border: 1px solid #94a3b8;
    border-radius: 6px;
    background: #1e293b;
    color: #f8fafc;
    font-size: 16px;
}
#tip {
    position: fixed;
    z-index: 10;
    max-width: calc(100vw - 20px);
    padding: 10px 13px;
    border: 1px solid #94a3b8;
    border-radius: 10px;
    background: #1e293b;
    color: #ffffff;
    box-shadow: 0 5px 18px rgba(0,0,0,.4);
    font-size: 13px;
    line-height: 1.5;
    pointer-events: none;
}
#tip[hidden] { display: none; }
#tip-title { font-weight: 700; }
</style>
</head>
<body>
<p class="hint">Tap a bar for its 5 kg range and record count.</p>
<svg id="chart" role="group" aria-label="Horse-weight histogram"></svg>
<div id="legend" class="legend"></div>
<label for="range">Select a range, including empty bins</label>
<select id="range">
    <option value="">Select a 5 kg range</option>
</select>
<div id="tip" role="tooltip" hidden>
    <div id="tip-title"></div>
    <div id="tip-count"></div>
    <div id="tip-boundary"></div>
</div>
<script>
"use strict";
const data = __DATA__;
const svg = document.getElementById("chart");
const tip = document.getElementById("tip");
const selector = document.getElementById("range");
const ns = "http://www.w3.org/2000/svg";
const colors = {
    "Mean": "#fbbf24",
    "Mean - 1 SD": "#f472b6",
    "Mean + 1 SD": "#34d399"
};
let pinned = false;
let active = null;
let activeAnchor = null;
let bars = [];

function element(tag, attributes, text) {
    const item = document.createElementNS(ns, tag);
    Object.keys(attributes).forEach(function(key) {
        item.setAttribute(key, attributes[key]);
    });
    if (text !== undefined) item.textContent = text;
    svg.appendChild(item);
    return item;
}

function positionTip(anchor) {
    const rect = anchor.getBoundingClientRect();
    tip.style.left = "10px";
    tip.style.top = "10px";
    const width = tip.offsetWidth;
    const height = tip.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const left = Math.max(
        10,
        Math.min(rect.left + rect.width / 2 - width / 2, vw - width - 10)
    );
    let top = rect.top - height - 8;
    if (top < 8) top = rect.bottom + 8;
    top = Math.max(8, Math.min(top, vh - height - 8));
    tip.style.left = left + "px";
    tip.style.top = top + "px";
}

function show(index, anchor) {
    const bin = data.bins[index];
    if (active !== null) bars[active].classList.remove("highlight");
    active = index;
    activeAnchor = anchor;
    bars[index].classList.add("highlight");

    document.getElementById("tip-title").textContent =
        bin.lower + "–" + bin.upper + " kg";
    document.getElementById("tip-count").textContent =
        "Records: " + bin.count.toLocaleString();
    document.getElementById("tip-boundary").textContent =
        index === data.bins.length - 1
        ? "Both endpoints included"
        : "Lower bound included; upper bound excluded";

    tip.hidden = false;
    positionTip(anchor);
}

function hide() {
    if (active !== null) bars[active].classList.remove("highlight");
    active = null;
    activeAnchor = null;
    pinned = false;
    tip.hidden = true;
}

data.bins.forEach(function(bin, index) {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent =
        bin.lower + "–" + bin.upper + " kg — " + bin.count + " records";
    selector.appendChild(option);
});

selector.addEventListener("change", function() {
    if (selector.value === "") {
        hide();
        return;
    }
    pinned = true;
    show(Number(selector.value), selector);
});

function draw() {
    hide();
    svg.replaceChildren();
    bars = [];

    const width = Math.max(280, svg.clientWidth);
    const height = 235;
    const left = 38;
    const right = 10;
    const top = 14;
    const bottom = 42;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const maximum = Math.max(1, ...data.bins.map(function(b) {
        return b.count;
    }));
    const upperCount = Math.max(1, Math.ceil(maximum * 1.12));
    const x = function(weight) {
        return left + (weight - 350) / 300 * plotWidth;
    };
    const y = function(count) {
        return top + plotHeight - count / upperCount * plotHeight;
    };

    svg.setAttribute("viewBox", "0 0 " + width + " " + height);

    const ticks = [...new Set([
        0,
        Math.round(upperCount / 2),
        upperCount
    ])];

    ticks.forEach(function(tick) {
        element("line", {
            x1: left, x2: width - right,
            y1: y(tick), y2: y(tick),
            stroke: "#334155"
        });
        element("text", {
            x: left - 6, y: y(tick) + 4,
            "text-anchor": "end",
            fill: "#cbd5e1", "font-size": 11
        }, tick);
    });

    [350, 400, 450, 500, 550, 600, 650].forEach(function(tick) {
        element("text", {
            x: x(tick), y: height - 24,
            "text-anchor": "middle",
            fill: "#f8fafc", "font-size": 10
        }, tick);
    });

    element("text", {
        x: left + plotWidth / 2, y: height - 5,
        "text-anchor": "middle",
        fill: "#cbd5e1", "font-size": 11
    }, "Horse weight (kg)");

    element("text", {
        x: left, y: 10,
        fill: "#cbd5e1", "font-size": 10
    }, "Records");

    data.bins.forEach(function(bin) {
        const bar = element("rect", {
            x: x(bin.lower) + 0.5,
            y: y(bin.count),
            width: Math.max(0.5, x(bin.upper) - x(bin.lower) - 1),
            height: top + plotHeight - y(bin.count),
            fill: "#60a5fa"
        });
        bars.push(bar);
    });

    data.references.forEach(function(reference) {
        if (reference.weight < 350 || reference.weight > 650) return;
        element("line", {
            x1: x(reference.weight), x2: x(reference.weight),
            y1: top, y2: top + plotHeight,
            stroke: colors[reference.label] || "#ffffff",
            "stroke-width": 2,
            "pointer-events": "none"
        });
    });

    // Full-height transparent targets also allow empty bins to be tapped.
    data.bins.forEach(function(bin, index) {
        const hit = element("rect", {
            x: x(bin.lower),
            y: top,
            width: x(bin.upper) - x(bin.lower),
            height: plotHeight,
            fill: "transparent",
            class: "hit",
            tabindex: 0,
            role: "button",
            "aria-label":
                bin.lower + " to " + bin.upper + " kg, " +
                bin.count + " records",
            "aria-describedby": "tip"
        });

        hit.addEventListener("click", function(event) {
            event.stopPropagation();
            pinned = true;
            selector.value = String(index);
            show(index, hit);
        });

        hit.addEventListener("pointerenter", function(event) {
            if (event.pointerType === "mouse" && !pinned) show(index, hit);
        });

        hit.addEventListener("pointerleave", function(event) {
            if (event.pointerType === "mouse" && !pinned) hide();
        });

        hit.addEventListener("focus", function() {
            if (!pinned) show(index, hit);
        });

        hit.addEventListener("blur", function() {
            if (!pinned) hide();
        });

        hit.addEventListener("keydown", function(event) {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                pinned = true;
                selector.value = String(index);
                show(index, hit);
            }
        });
    });
}

const legend = document.getElementById("legend");
data.references.forEach(function(reference) {
    const item = document.createElement("span");
    item.style.color = colors[reference.label] || "#ffffff";
    item.textContent =
        reference.label + ": " + reference.weight.toFixed(1) + " kg";
    legend.appendChild(item);
});

document.addEventListener("click", function(event) {
    if (
        !event.target.closest(".hit") &&
        !event.target.closest("#range")
    ) hide();
});

document.addEventListener("keydown", function(event) {
    if (event.key === "Escape") hide();
});

let resizeTimer;
window.addEventListener("resize", function() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 100);
});

draw();
</script>
</body>
</html>
"""

    components.html(
        template.replace("__DATA__", payload),
        height=440,
        scrolling=False,
    )

'''


class ReplaceChartCall(ast.NodeTransformer):
    def __init__(self):
        self.count = 0

    def visit_Call(self, node):
        node = self.generic_visit(node)

        direct_vega = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "vega_lite_chart"
        )

        lightweight_wrapper = (
            isinstance(node.func, ast.Name)
            and node.func.id == "_older_device_vega_lite_chart"
        )

        if direct_vega or lightweight_wrapper:
            node.func = ast.Name(
                id="_render_touch_weight_histogram",
                ctx=ast.Load(),
            )
            self.count += 1

        return node


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

    if "# WEIGHT_CHART_FIXED_FIVE_KG_BINS_V1" not in source:
        raise ValueError(
            "Apply scripts/fix-weight-chart-scale.py first."
        )

    tree = ast.parse(source)
    function = find_function(tree, TARGET_FUNCTION)

    if function.decorator_list:
        raise ValueError("Unexpected decorators on the weight-chart helper.")

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_render_touch_weight_histogram"
        for node in tree.body
    ):
        raise ValueError("A touch histogram helper already exists.")

    start = function.lineno - 1
    end = function.end_lineno

    transformer = ReplaceChartCall()
    transformed = transformer.visit(function)

    if transformer.count != 1:
        raise ValueError(
            "Expected exactly one weight-chart rendering call."
        )

    ast.fix_missing_locations(transformed)
    lines = source.splitlines(keepends=True)

    updated = (
        "".join(lines[:start])
        + HELPER.strip("\n")
        + "\n\n"
        + ast.unparse(transformed)
        + "\n\n"
        + "".join(lines[end:])
    )

    compile(updated, "<touch-weight-histogram>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in {
                    TARGET_FUNCTION,
                    "_render_touch_weight_histogram",
                }
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the weight-chart functions."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid touch-tooltip patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description="Add tap tooltips to the fixed 5 kg weight histogram."
    )
    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to update. Default: app.py",
    )

    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if PATCH_MARKER in source:
        print(f"The touch-tooltip fix is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup = app_path.with_name(
        f"{app_path.name}.before-touch-weight-tooltips.bak"
    )

    if backup.exists():
        raise SystemExit(
            f"Backup already exists: {backup}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(app_path, backup)
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
    print(f"Backup: {backup}")
    print("Python syntax and patch-scope validation passed.")
    print("Tap a histogram bar to show its range and record count.")
    print("A range selector also provides access to narrow and empty bins.")
    print("Existing weight calculations and restrictions are unchanged.")
    print("Lightweight mode continues to display text summaries.")
    print("Turn off Lightweight mode to use the interactive histogram.")
    print("Restart or redeploy the app, then reload the chart.")
    print("Physical iPad and other touch-device testing is still required.")


if __name__ == "__main__":
    main()
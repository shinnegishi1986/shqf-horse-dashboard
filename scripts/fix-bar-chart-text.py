# script/fix-bar-chart-text.py
#
# Fixes unreadable labels in the embedded stacked horizontal charts.
#
# Uses a self-contained dark chart panel with explicit light text colors,
# rather than relying on inherited Streamlit or browser theme colors.
#
# Preserves touch tooltips, mouse hover, chart data, and filtering behavior.
#
# Run from the project root:
#   python script/fix-bar-chart-text.py
#
# Or specify the application file:
#   python script/fix-bar-chart-text.py app.py

import argparse
import ast
from pathlib import Path
import re
import shutil
import tempfile


PATCH_MARKER = "# STACKED_BAR_CHART_TEXT_CONTRAST_V1"

CHART_CSS = """
<style>
    :root {
        color-scheme: dark;
        --foreground: #f8fafc;
        --background: #111827;
        --border: #94a3b8;
        --muted: #cbd5e1;
    }

    * {
        box-sizing: border-box;
    }

    html {
        color: #f8fafc !important;
        background: #111827 !important;
    }

    body {
        margin: 0;
        padding: 10px 8px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 13px;
        color: #f8fafc !important;
        background: #111827 !important;
        -webkit-text-fill-color: #f8fafc;
    }

    .hint {
        margin: 0 0 12px;
        color: #cbd5e1 !important;
        -webkit-text-fill-color: #cbd5e1 !important;
        font-size: 12px;
    }

    .bar {
        display: flex;
        width: 100%;
        height: 48px;
        overflow: hidden;
        border-radius: 6px;
        background: #334155;
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
        box-shadow: inset 0 0 0 3px #ffffff;
        outline: none;
    }

    .axis {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        margin-top: 7px;
        color: #cbd5e1 !important;
        font-size: 11px;
    }

    .axis span {
        color: #cbd5e1 !important;
        -webkit-text-fill-color: #cbd5e1 !important;
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
        color: #f8fafc !important;
        background: #111827 !important;
        scrollbar-color: #64748b #111827;
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
        color: #f8fafc !important;
        -webkit-text-fill-color: #f8fafc !important;
        background: #111827 !important;
        text-align: left;
        cursor: pointer;
        touch-action: manipulation;
        opacity: 1;
    }

    .legend-item:hover {
        background: #1e293b !important;
    }

    .legend-item:focus-visible {
        outline: 2px solid #ffffff;
        outline-offset: -2px;
        background: #1e293b !important;
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
        color: #f8fafc !important;
        -webkit-text-fill-color: #f8fafc !important;
    }

    #tooltip {
        position: fixed;
        z-index: 1000;
        max-width: min(300px, calc(100vw - 16px));
        padding: 11px 13px;
        border: 1px solid #94a3b8;
        border-radius: 11px;
        color: #f8fafc !important;
        background: #1e293b !important;
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
        pointer-events: none;
        overflow-wrap: anywhere;
        font-size: 13px;
        line-height: 1.5;
    }

    #tooltip[hidden] {
        display: none;
    }

    #tooltip-title,
    #tooltip-count,
    #tooltip-share {
        color: #f8fafc !important;
        -webkit-text-fill-color: #f8fafc !important;
    }

    .tooltip-title {
        font-weight: 700;
        margin-bottom: 3px;
    }

    .tooltip-note {
        margin-top: 4px;
        font-size: 11px;
        color: #cbd5e1 !important;
        -webkit-text-fill-color: #cbd5e1 !important;
    }
</style>
"""


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_review_stacked_count_chart"
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one _render_review_stacked_count_chart "
            "function."
        )

    renderer = matches[0]

    if renderer.decorator_list:
        raise ValueError(
            "Unexpected renderer decorators. No changes were applied."
        )

    lines = source.splitlines(keepends=True)
    renderer_source = "".join(
        lines[renderer.lineno - 1:renderer.end_lineno]
    )

    if "components.html(" not in renderer_source:
        raise ValueError(
            "The embedded HTML chart renderer was not found. "
            "Apply fix-bar-charts-tooltip-in-apple-device.py first."
        )

    style_pattern = re.compile(
        r"<style\b[^>]*>.*?</style>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    if len(style_pattern.findall(renderer_source)) != 1:
        raise ValueError(
            "Expected one embedded chart style block. "
            "No changes were applied."
        )

    patched_renderer = style_pattern.sub(
        lambda match: CHART_CSS.strip(),
        renderer_source,
        count=1,
    )

    updated = (
        "".join(lines[:renderer.lineno - 1])
        + PATCH_MARKER
        + "\n"
        + patched_renderer
        + "".join(lines[renderer.end_lineno:])
    )

    compile(updated, "<chart-text-contrast-patch>", "exec")

    validate_changes(source, updated)

    return updated


def validate_changes(original, updated):
    function_name = "_render_review_stacked_count_chart"

    def split_tree(source):
        tree = ast.parse(source)
        renderer = None
        other_nodes = []

        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == function_name
            ):
                renderer = node
            else:
                other_nodes.append(node)

        return (
            renderer,
            ast.dump(
                ast.Module(body=other_nodes, type_ignores=[]),
                include_attributes=False,
            ),
        )

    old_renderer, old_rest = split_tree(original)
    new_renderer, new_rest = split_tree(updated)

    if old_rest != new_rest:
        raise ValueError(
            "Unexpected changes outside the chart renderer."
        )

    class NormalizeStyles(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and "<style" in node.value.lower():
                normalized = re.sub(
                    r"<style\b[^>]*>.*?</style>",
                    "<style>CHART_STYLES</style>",
                    node.value,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                return ast.copy_location(
                    ast.Constant(value=normalized),
                    node,
                )
            return node

    old_normalized = NormalizeStyles().visit(old_renderer)
    new_normalized = NormalizeStyles().visit(new_renderer)

    if ast.dump(
        old_normalized,
        include_attributes=False,
    ) != ast.dump(
        new_normalized,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes beyond the chart CSS."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fix stacked bar chart labels and tooltip text "
            "with explicit high-contrast colors."
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
        print("The bar chart text contrast patch is already applied.")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-bar-chart-text-fix.bak"
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
    print("Python syntax and CSS-only change validation passed.")
    print("Charts now use explicit light text on a dark chart panel.")
    print("Touch tooltips and existing application logic were preserved.")
    print("Reload the application to view the changes.")
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
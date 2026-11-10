# scripts/add-older-device-support.py
#
# Adds lightweight rendering for older or memory-constrained devices.
#
# Run:
#   python scripts/add-older-device-support.py
#
# Or specify the application file:
#   python scripts/add-older-device-support.py app.py
#
# Behavior:
#   - Lightweight mode is enabled by default.
#   - Adds a sidebar checkbox to enable/disable lightweight mode.
#   - Replaces custom stacked charts with compact text summaries.
#   - Replaces the optional weight chart with compact histogram text.
#   - Keeps existing filters, calculations, and metrics.
#   - Does not change authentication or disable security settings.
#
# IMPORTANT:
#   This is an application-level rendering fallback.
#   It cannot repair a Streamlit frontend that fails before Python-rendered
#   content appears. It does not guarantee support for every iOS 16 release.
#
# Does not downgrade Streamlit or modify dependency requirements.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# OLDER_DEVICE_LIGHTWEIGHT_RENDERING_V1"


HELPERS = r'''
# OLDER_DEVICE_LIGHTWEIGHT_RENDERING_V1
def _older_device_lightweight_enabled():
    return bool(
        st.session_state.get(
            "older_device_lightweight_mode",
            True,
        )
    )


def render_older_device_settings():
    st.sidebar.checkbox(
        "Lightweight mode",
        value=True,
        key="older_device_lightweight_mode",
        help=(
            "Use text summaries instead of interactive charts. "
            "Turn off on devices where charts work reliably."
        ),
    )


def _older_device_render_stacked_summary(
    title,
    rows,
    total,
    category_count,
):
    st.markdown(f"### {title}")

    if not rows or total <= 0:
        st.info("No matching records.")
        return

    st.caption(
        f"{total:,} records across {category_count:,} categories"
    )

    # Rows are already aggregated and ordered by the existing chart helper.
    # Use text rather than iframe, Vega, or dataframe rendering.
    for row in rows[:21]:
        category = str(row.get("category", "Unknown"))
        count = row.get("count", 0)

        try:
            numeric_count = float(count)
            percentage = numeric_count / total * 100
            count_text = f"{numeric_count:,.0f}"
            share_text = f"{percentage:.1f}%"
        except (TypeError, ValueError, ZeroDivisionError):
            count_text = str(count)
            share_text = "N/A"

        st.text(f"{category}: {count_text} ({share_text})")


def _older_device_vega_lite_chart(data, *args, **kwargs):
    if not _older_device_lightweight_enabled():
        return st.vega_lite_chart(data, *args, **kwargs)

    st.caption("Weight histogram — lightweight view")

    # The existing optional weight chart has already calculated its
    # mean, standard deviation, and bounded histogram bins.
    if not isinstance(data, pd.DataFrame):
        st.info("Interactive chart hidden in lightweight mode.")
        return

    required_columns = {"from_weight", "to_weight", "count"}

    if not required_columns.issubset(data.columns):
        st.info("Interactive chart hidden in lightweight mode.")
        return

    for lower, upper, count in data[
        ["from_weight", "to_weight", "count"]
    ].head(24).itertuples(index=False, name=None):
        st.text(
            f"{float(lower):,.1f}–{float(upper):,.1f} kg: "
            f"{int(count):,} records"
        )

'''


def find_function(tree, name, required=True):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if not matches and not required:
        return None

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {name} function; found {len(matches)}."
        )

    return matches[0]


def is_streamlit_vega_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "vega_lite_chart"
    )


class ReplaceOptionalWeightChart(ast.NodeTransformer):
    def __init__(self):
        self.count = 0

    def visit_Call(self, node):
        node = self.generic_visit(node)

        if is_streamlit_vega_call(node):
            node.func = ast.Name(
                id="_older_device_vega_lite_chart",
                ctx=ast.Load(),
            )
            self.count += 1

        return node


def function_replacement(node):
    ast.fix_missing_locations(node)
    return ast.unparse(node) + "\n\n"


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)
    main_function = find_function(tree, "main")
    stacked_renderer = find_function(
        tree,
        "_render_review_stacked_count_chart",
    )
    weight_renderer = find_function(
        tree,
        "render_review_weight_standard_distribution",
        required=False,
    )

    for function in (main_function, stacked_renderer, weight_renderer):
        if function is not None and function.decorator_list:
            raise ValueError(
                f"Unexpected decorators on {function.name}."
            )

    helper_names = {
        "_older_device_lightweight_enabled",
        "render_older_device_settings",
        "_older_device_render_stacked_summary",
        "_older_device_vega_lite_chart",
    }

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name in helper_names
        for node in tree.body
    ):
        raise ValueError(
            "Older-device helpers already exist without the expected marker."
        )

    lines = source.splitlines(keepends=True)
    edits = []

    # Insert before the existing renderer body without rewriting its HTML,
    # JavaScript, dark-mode styling, or touch-tooltip implementation.
    first_statement = stacked_renderer.body[0]

    if (
        isinstance(first_statement, ast.Expr)
        and isinstance(first_statement.value, ast.Constant)
        and isinstance(first_statement.value.value, str)
    ):
        if len(stacked_renderer.body) < 2:
            raise ValueError("The stacked chart renderer has no body.")
        insertion_line = stacked_renderer.body[1].lineno - 1
    else:
        insertion_line = first_statement.lineno - 1

    fallback = '''
    if _older_device_lightweight_enabled():
        _older_device_render_stacked_summary(
            title,
            rows,
            total,
            category_count,
        )
        return

'''

    edits.append((insertion_line, insertion_line, fallback))

    # Put the setting before main() performs routing, so chart renderers
    # read the current checkbox state during the same run.
    main_start = main_function.body[0].lineno - 1

    edits.append(
        (
            main_start,
            main_start,
            "    render_older_device_settings()\n\n",
        )
    )

    if weight_renderer is not None:
        transformer = ReplaceOptionalWeightChart()
        transformed = transformer.visit(weight_renderer)

        if transformer.count != 1:
            raise ValueError(
                "Expected exactly one Vega chart in the optional "
                "weight-distribution helper."
            )

        edits.append(
            (
                weight_renderer.lineno - 1,
                weight_renderer.end_lineno,
                function_replacement(transformed),
            )
        )

    # Define helpers before any application function uses them.
    first_function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        None,
    )

    if first_function is None:
        raise ValueError("No application functions were found.")

    helper_line = (
        min(node.lineno for node in first_function.decorator_list) - 1
        if first_function.decorator_list
        else first_function.lineno - 1
    )

    edits.append(
        (
            helper_line,
            helper_line,
            HELPERS.strip("\n") + "\n\n",
        )
    )

    # Larger original line positions are edited first.
    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<older-device-support>", "exec")

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid older-device patch marker.")

    updated_tree = ast.parse(updated)

    for name in helper_names:
        find_function(updated_tree, name)

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add a default-on lightweight chart-rendering mode "
            "for older devices."
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
        print(f"Lightweight mode is already installed in: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-older-device-support.bak"
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
    print("Python syntax validation passed.")
    print("Added default-on Lightweight mode in the sidebar.")
    print("Charts use compact text summaries while this mode is enabled.")
    print("Disable Lightweight mode to restore interactive charts.")
    print("Restart or redeploy the application.")
    print("Testing on the affected physical device is still required.")
    print(
        "If even the login page remains blank, this patch cannot fix "
        "the Streamlit frontend startup failure. Check the deployed "
        "Streamlit version, exact iOS version, and browser error logs."
    )


if __name__ == "__main__":
    main()
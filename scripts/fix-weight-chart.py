# scripts/fix-weight-chart.py
#
# Fixes the weight-chart error:
#   TypeError: Cannot create property 'bottom' on number '10'
#
# The earlier chart specification used:
#   "padding": 10
#
# This patch replaces that numeric padding with explicit per-side padding:
#   "padding": {"left": 10, "top": 10, "right": 10, "bottom": 10}
#
# Vega-Lite supports this object form. [18]
#
# Run:
#   python scripts/fix-weight-chart.py
#
# Or specify the application file:
#   python scripts/fix-weight-chart.py app.py
#
# Preserves:
#   - Optional chart visibility.
#   - Weight calculations and filtered-result scope.
#   - Responsive container width.
#   - Lightweight mode, if installed.
#   - Existing filters, charts, and other application features.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# WEIGHT_CHART_EXPLICIT_PADDING_FIX_V1"
TARGET_FUNCTION = "render_review_weight_standard_distribution"


def find_weight_chart_function(tree):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == TARGET_FUNCTION
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {TARGET_FUNCTION} function; "
            f"found {len(matches)}."
        )

    return matches[0]


def source_offset(lines, line_number, byte_column):
    # AST column offsets use UTF-8 bytes, not Unicode character counts.
    line = lines[line_number - 1]
    character_column = len(
        line.encode("utf-8")[:byte_column].decode("utf-8")
    )

    return (
        sum(len(value) for value in lines[:line_number - 1])
        + character_column
    )


def find_spec_assignment(function):
    matches = []

    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name)
            and target.id == "spec"
            for target in node.targets
        ):
            continue

        if isinstance(node.value, ast.Dict):
            matches.append(node)

    if len(matches) != 1:
        raise ValueError(
            "Could not uniquely locate the weight chart's spec dictionary."
        )

    return matches[0]


def patch_application(source):
    tree = ast.parse(source)
    function = find_weight_chart_function(tree)
    assignment = find_spec_assignment(function)
    specification = assignment.value

    padding_values = [
        value
        for key, value in zip(
            specification.keys,
            specification.values,
        )
        if isinstance(key, ast.Constant) and key.value == "padding"
    ]

    if len(padding_values) != 1:
        raise ValueError(
            "Expected exactly one top-level padding entry "
            "in the weight chart specification."
        )

    padding = padding_values[0]

    if isinstance(padding, ast.Dict):
        print("The weight chart already uses object-form padding.")
        return source, False

    if not (
        isinstance(padding, ast.Constant)
        and type(padding.value) in (int, float)
        and padding.value >= 0
    ):
        raise ValueError(
            "Unexpected padding expression. "
            "The application was not changed."
        )

    value = padding.value

    replacement = (
        "{"
        f'"left": {value!r}, '
        f'"top": {value!r}, '
        f'"right": {value!r}, '
        f'"bottom": {value!r}'
        "}"
    )

    lines = source.splitlines(keepends=True)

    start = source_offset(
        lines,
        padding.lineno,
        padding.col_offset,
    )

    end = source_offset(
        lines,
        padding.end_lineno,
        padding.end_col_offset,
    )

    updated = source[:start] + replacement + source[end:]

    if PATCH_MARKER not in updated:
        updated += "\n\n" + PATCH_MARKER + "\n"

    compile(updated, "<weight-chart-padding-fix>", "exec")
    validate_patch(source, updated)

    return updated, True


def validate_patch(original, updated):
    original_tree = ast.parse(original)
    updated_tree = ast.parse(updated)

    original_function = find_weight_chart_function(original_tree)
    updated_function = find_weight_chart_function(updated_tree)

    original_spec = find_spec_assignment(original_function).value
    updated_spec = find_spec_assignment(updated_function).value

    original_index = next(
        index
        for index, key in enumerate(original_spec.keys)
        if isinstance(key, ast.Constant) and key.value == "padding"
    )

    updated_index = next(
        index
        for index, key in enumerate(updated_spec.keys)
        if isinstance(key, ast.Constant) and key.value == "padding"
    )

    original_padding = original_spec.values[original_index]
    updated_padding = updated_spec.values[updated_index]

    expected = {
        "left": original_padding.value,
        "top": original_padding.value,
        "right": original_padding.value,
        "bottom": original_padding.value,
    }

    if ast.literal_eval(updated_padding) != expected:
        raise ValueError("The replacement padding object is invalid.")

    # Normalize only the intended padding change, then compare the whole app.
    updated_spec.values[updated_index] = ast.Constant(
        value=original_padding.value
    )

    if ast.dump(
        original_tree,
        include_attributes=False,
    ) != ast.dump(
        updated_tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes outside the weight chart padding."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fix the weight chart's numeric-padding frontend error "
            "by using explicit per-side padding."
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

    try:
        updated, changed = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    if not changed:
        print(f"No changes needed in: {app_path}")
        return

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-chart-padding-fix.bak"
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
    print("Python syntax and padding-only change validation passed.")
    print("Replaced numeric chart padding with explicit per-side padding.")
    print("Weight calculations and other application behavior are unchanged.")
    print("Restart or redeploy the application, then reload the browser.")
    print("Enable the weight chart to verify frontend rendering.")


if __name__ == "__main__":
    main()
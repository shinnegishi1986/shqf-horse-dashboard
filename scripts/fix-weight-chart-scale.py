# scripts/fix-weight-chart-scale.py
#
# Changes the horse-weight histogram to fixed 5 kg bins:
#   350–355, 355–360, ... 420–425, 425–430, ... 645–650.
#
# Boundary rules:
#   - Each bin includes its lower bound and excludes its upper bound.
#   - The final bin also includes 650 kg.
#   - For example, 425 kg belongs to the 425–430 kg bin.
#
# Preserves:
#   - Top-three finishers only: positions 1, 2, or 3.
#   - Weight range: 350–650 kg inclusive.
#   - Existing mean and sample standard deviation calculations.
#   - Optional chart visibility and filtered-result selection.
#   - Responsive layout and explicit-padding fix.
#   - Lightweight mode, if installed.
#
# Run:
#   python scripts/fix-weight-chart-scale.py
#
# Or specify the application file:
#   python scripts/fix-weight-chart-scale.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# WEIGHT_CHART_FIXED_FIVE_KG_BINS_V1"
RANGE_MARKER = "# WEIGHT_CHART_RANGE_350_TO_650_V1"
CONDITION_MARKER = "# WEIGHT_CHART_TOP_THREE_CONDITION_V1"

TARGET_FUNCTION = "render_review_weight_standard_distribution"
LIGHTWEIGHT_FUNCTION = "_older_device_vega_lite_chart"


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


class UpdateHistogramScale(ast.NodeTransformer):
    def __init__(self):
        self.bin_count_updates = 0
        self.bin_width_updates = 0

    def visit_Assign(self, node):
        node = self.generic_visit(node)

        if len(node.targets) != 1:
            return node

        target = node.targets[0]

        if not isinstance(target, ast.Name):
            return node

        if target.id == "bin_count":
            # (650 - 350) / 5 = 60 bins.
            node.value = ast.Constant(value=60)
            self.bin_count_updates += 1

        elif target.id == "bin_width":
            node.value = ast.Constant(value=5.0)
            self.bin_width_updates += 1

        return node


class UpdateLightweightHistogramLimit(ast.NodeTransformer):
    def __init__(self):
        self.updates = 0

    def visit_Call(self, node):
        node = self.generic_visit(node)

        # The lightweight renderer previously displayed only 24 bins.
        # Raise that limit so all 60 fixed-width bins remain available.
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "head"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 24
        ):
            node.args[0] = ast.Constant(value=60)
            self.updates += 1

        return node


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    for marker, script_name in (
        (RANGE_MARKER, "scripts/fix-weight-chart-range.py"),
        (CONDITION_MARKER, "scripts/fix-weight-chart-condition.py"),
    ):
        if marker not in source:
            raise ValueError(
                f"Apply {script_name} before applying this patch."
            )

    tree = ast.parse(source)
    chart_function = find_function(tree, TARGET_FUNCTION)

    if chart_function.decorator_list:
        raise ValueError(
            "Unexpected decorators on the weight-chart function."
        )

    chart_start = chart_function.lineno - 1
    chart_end = chart_function.end_lineno

    transformer = UpdateHistogramScale()
    updated_chart = transformer.visit(chart_function)

    if transformer.bin_count_updates != 1:
        raise ValueError(
            "Could not uniquely identify the histogram bin count."
        )

    if transformer.bin_width_updates != 1:
        raise ValueError(
            "Could not uniquely identify the histogram bin width."
        )

    ast.fix_missing_locations(updated_chart)

    edits = [
        (
            chart_start,
            chart_end,
            PATCH_MARKER
            + "\n"
            + ast.unparse(updated_chart)
            + "\n\n",
        )
    ]

    lightweight_function = find_function(
        tree,
        LIGHTWEIGHT_FUNCTION,
        required=False,
    )

    if lightweight_function is not None:
        if lightweight_function.decorator_list:
            raise ValueError(
                "Unexpected decorators on the lightweight chart helper."
            )

        lightweight_start = lightweight_function.lineno - 1
        lightweight_end = lightweight_function.end_lineno

        lightweight_transformer = UpdateLightweightHistogramLimit()
        updated_lightweight = lightweight_transformer.visit(
            lightweight_function
        )

        if lightweight_transformer.updates > 1:
            raise ValueError(
                "Found multiple unexpected lightweight histogram limits."
            )

        if lightweight_transformer.updates == 1:
            ast.fix_missing_locations(updated_lightweight)

            edits.append(
                (
                    lightweight_start,
                    lightweight_end,
                    ast.unparse(updated_lightweight) + "\n\n",
                )
            )

    lines = source.splitlines(keepends=True)

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<weight-chart-five-kg-bins>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    allowed_functions = {
        TARGET_FUNCTION,
        LIGHTWEIGHT_FUNCTION,
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in allowed_functions
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the weight-chart helpers."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid fixed-bin patch marker.")

    tree = ast.parse(updated)
    chart_function = find_function(tree, TARGET_FUNCTION)

    assignments = {}

    for node in ast.walk(chart_function):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        ):
            assignments[node.targets[0].id] = node.value.value

    required_values = {
        "lower_bound": 350.0,
        "upper_bound": 650.0,
        "bin_count": 60,
        "bin_width": 5.0,
    }

    for name, expected in required_values.items():
        if assignments.get(name) != expected:
            raise ValueError(
                f"Unexpected histogram setting for {name}: "
                f"{assignments.get(name)!r}"
            )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Use fixed 5 kg histogram bars for the top-three "
            "horse-weight distribution chart."
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
        print(f"Fixed 5 kg histogram bins are already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-chart-five-kg-bins.bak"
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
    print("Histogram bars now represent fixed 5 kg intervals.")
    print("Examples: 420–425 kg, 425–430 kg, 430–435 kg.")
    print("Top-three and 350–650 kg restrictions are preserved.")
    print("Weight statistics are unchanged.")
    print("Lightweight mode displays up to all 60 histogram bins.")
    print("Restart or redeploy the app, then reload the weight chart.")
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
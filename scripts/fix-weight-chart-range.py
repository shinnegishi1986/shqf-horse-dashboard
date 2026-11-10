# scripts/fix-weight-chart-range.py
#
# Restricts the horse-weight distribution chart to 350–650 kg inclusive.
#
# Weights below 350 kg or above 650 kg are excluded from:
#   - Histogram counts.
#   - Mean weight.
#   - Sample standard deviation.
#   - Minimum and maximum weight metrics.
#
# This affects only the optional weight-distribution section.
# Checklist records, review filters, and other summary metrics are unchanged.
#
# Run:
#   python scripts/fix-weight-chart-range.py
#
# Or specify the application file:
#   python scripts/fix-weight-chart-range.py app.py
#
# Preserves the explicit-padding fix and optional lightweight mode.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# WEIGHT_CHART_RANGE_350_TO_650_V1"
TARGET_FUNCTION = "render_review_weight_standard_distribution"


def find_function(tree):
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


class UpdateWeightRange(ast.NodeTransformer):
    def __init__(self):
        self.validation_updates = 0
        self.bin_updates = 0
        self.domain_updates = set()
        self.caption_updates = 0

    def visit_If(self, node):
        # Identify the existing weight-validation condition.
        if ast.dump(
            node.test,
            include_attributes=False,
        ) == ast.dump(
            ast.parse(
                "not math.isfinite(weight) or weight <= 0",
                mode="eval",
            ).body,
            include_attributes=False,
        ):
            node.test = ast.parse(
                "not math.isfinite(weight) or not 350.0 <= weight <= 650.0",
                mode="eval",
            ).body

            self.validation_updates += 1
            return node

        # Replace the original variable-range histogram setup.
        if ast.dump(
            node.test,
            include_attributes=False,
        ) == ast.dump(
            ast.parse(
                "minimum == maximum",
                mode="eval",
            ).body,
            include_attributes=False,
        ):
            self.bin_updates += 1

            return ast.parse(
                """
bin_count = min(24, max(5, math.ceil(math.sqrt(count))))
lower_bound = 350.0
upper_bound = 650.0
"""
            ).body

        return self.generic_visit(node)

    def visit_Assign(self, node):
        node = self.generic_visit(node)

        if len(node.targets) != 1:
            return node

        target = node.targets[0]

        if not isinstance(target, ast.Name):
            return node

        replacements = {
            "domain_minimum": 350.0,
            "domain_maximum": 650.0,
            "padding": 0.0,
        }

        if target.id in replacements:
            node.value = ast.Constant(
                value=replacements[target.id]
            )
            self.domain_updates.add(target.id)

        return node

    def visit_Constant(self, node):
        if not isinstance(node.value, str):
            return node

        if (
            "missing or invalid weight(s) excluded."
            in node.value
        ):
            node.value = node.value.replace(
                "missing or invalid weight(s) excluded.",
                "weight(s) excluded: missing, invalid, or outside "
                "350–650 kg inclusive.",
            )
            self.caption_updates += 1

        elif node.value == (
            "No valid horse weights are available for these filters."
        ):
            node.value = (
                "No horse weights between 350 and 650 kg inclusive "
                "are available for these filters."
            )

        return node


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)
    function = find_function(tree)

    if function.decorator_list:
        raise ValueError(
            "Unexpected decorators on the weight-chart function."
        )

    start = function.lineno - 1
    end = function.end_lineno

    transformer = UpdateWeightRange()
    updated_function = transformer.visit(function)

    if transformer.validation_updates != 1:
        raise ValueError(
            "Could not uniquely identify the weight-validation condition."
        )

    if transformer.bin_updates != 1:
        raise ValueError(
            "Could not uniquely identify the histogram range setup."
        )

    if transformer.domain_updates != {
        "domain_minimum",
        "domain_maximum",
        "padding",
    }:
        raise ValueError(
            "Could not identify all chart-domain settings."
        )

    if transformer.caption_updates != 1:
        raise ValueError(
            "Could not uniquely identify the excluded-weight caption."
        )

    ast.fix_missing_locations(updated_function)

    lines = source.splitlines(keepends=True)

    updated = (
        "".join(lines[:start])
        + PATCH_MARKER
        + "\n"
        + ast.unparse(updated_function)
        + "\n\n"
        + "".join(lines[end:])
    )

    compile(updated, "<weight-chart-range-fix>", "exec")
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
                and node.name == TARGET_FUNCTION
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the weight-distribution function."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid weight-range patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Restrict the optional horse-weight distribution chart "
            "and its statistics to 350–650 kg inclusive."
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
        print(f"The weight range fix is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-chart-range-fix.bak"
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
    print("Weight chart range: 350–650 kg inclusive.")
    print("Weights below 350 kg or above 650 kg are excluded.")
    print("Chart statistics use the same included weight records.")
    print("Checklist records and other review metrics are unchanged.")
    print("Restart or redeploy the app, then reload the weight chart.")
    print("Browser visual testing is still required.")


if __name__ == "__main__":
    main()
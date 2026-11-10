# scripts/fix-weight-chart-condition.py
#
# Restricts the optional weight-distribution chart to horses that
# finished in positions 1, 2, or 3.
#
# Preserves the existing 350–650 kg inclusive weight restriction.
#
# The histogram and its statistics will use records matching BOTH:
#   1. Finishing position is 1, 2, or 3.
#   2. Horse weight is between 350 and 650 kg inclusive.
#
# Uses actual filtered results before pagination.
# Respects the existing first-filter / second-filter chart selection.
#
# Does not change checklist records, review filters, or other metrics.
#
# Run:
#   python scripts/fix-weight-chart-condition.py
#
# Or specify the application file:
#   python scripts/fix-weight-chart-condition.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# WEIGHT_CHART_TOP_THREE_CONDITION_V1"
RANGE_MARKER = "# WEIGHT_CHART_RANGE_350_TO_650_V1"
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


class UpdateWeightCondition(ast.NodeTransformer):
    def __init__(self):
        self.loop_updates = 0
        self.excluded_updates = 0
        self.caption_updates = 0
        self.title_updates = 0

    def visit_For(self, node):
        node = self.generic_visit(node)

        if not (
            isinstance(node.target, ast.Name)
            and node.target.id == "entry"
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "records"
        ):
            return node

        self.loop_updates += 1

        top_three_condition = ast.parse(
            """
finished_place = clean_text(entry.get("finished_place"))

if (
    not finished_place.isdecimal()
    or int(finished_place) not in (1, 2, 3)
):
    non_top_three += 1
    continue
"""
        ).body

        node.body = top_three_condition + node.body

        return node

    def visit_Assign(self, node):
        node = self.generic_visit(node)

        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "excluded"
            and isinstance(node.value, ast.Constant)
            and node.value.value == 0
        ):
            self.excluded_updates += 1

            return [
                node,
                ast.Assign(
                    targets=[
                        ast.Name(
                            id="non_top_three",
                            ctx=ast.Store(),
                        )
                    ],
                    value=ast.Constant(value=0),
                ),
            ]

        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)

        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.args
        ):
            return node

        if (
            node.func.attr == "markdown"
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "### Horse-Weight Distribution"
        ):
            node.args[0] = ast.Constant(
                value="### Horse-Weight Distribution — Top 3"
            )
            self.title_updates += 1

        elif node.func.attr == "caption":
            argument = node.args[0]

            # Replace only the chart's scope/exclusion caption.
            if (
                isinstance(argument, ast.JoinedStr)
                and any(
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Name)
                    and part.value.id == "excluded"
                    for part in argument.values
                )
            ):
                node.args[0] = ast.parse(
                    'f"{scope} · {count:,} valid top-three weight record(s) · "'
                    'f"{non_top_three:,} record(s) outside finishing positions "'
                    '"1, 2, or 3 excluded · "'
                    'f"{excluded:,} top-three weight(s) excluded because "'
                    '"they are missing, invalid, or outside 350–650 kg inclusive. "'
                    '"Uses all matching checklist records before pagination."',
                    mode="eval",
                ).body

                self.caption_updates += 1

        elif (
            node.func.attr == "info"
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("No horse weights between")
        ):
            node.args[0] = ast.Constant(
                value=(
                    "No first-, second-, or third-place finishers with "
                    "horse weights between 350 and 650 kg inclusive "
                    "are available for these filters."
                )
            )

        return node

    def visit_Constant(self, node):
        if not isinstance(node.value, str):
            return node

        if node.value == (
            "Show horse-weight distribution and standard deviation"
        ):
            node.value = (
                "Show top-three horse-weight distribution "
                "and standard deviation"
            )

        elif node.value == (
            "Use second-filter results for the weight chart"
        ):
            node.value = (
                "Use second-filter results for the top-three weight chart"
            )

        elif node.value == "Mean Horse Weight":
            node.value = "Mean Horse Weight (Top 3)"

        elif node.value == "Standard Deviation":
            node.value = "Standard Deviation (Top 3)"

        elif node.value == "Minimum Weight":
            node.value = "Minimum Weight (Top 3)"

        elif node.value == "Maximum Weight":
            node.value = "Maximum Weight (Top 3)"

        return node


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    if RANGE_MARKER not in source:
        raise ValueError(
            "Apply scripts/fix-weight-chart-range.py first so the "
            "350–650 kg restriction is present."
        )

    tree = ast.parse(source)
    function = find_function(tree)

    if function.decorator_list:
        raise ValueError(
            "Unexpected decorators on the weight-chart function."
        )

    start = function.lineno - 1
    end = function.end_lineno

    transformer = UpdateWeightCondition()
    updated_function = transformer.visit(function)

    if transformer.loop_updates != 1:
        raise ValueError(
            "Could not uniquely identify the filtered-record weight loop."
        )

    if transformer.excluded_updates != 1:
        raise ValueError(
            "Could not uniquely identify the excluded-weight counter."
        )

    if transformer.caption_updates != 1:
        raise ValueError(
            "Could not uniquely identify the chart scope caption."
        )

    if transformer.title_updates != 1:
        raise ValueError(
            "Could not uniquely identify the weight-chart heading."
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

    compile(updated, "<weight-chart-top-three-condition>", "exec")
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
        raise ValueError("Invalid top-three weight-chart patch marker.")

    tree = ast.parse(updated)
    function = find_function(tree)

    expected_range_condition = ast.dump(
        ast.parse(
            "not math.isfinite(weight) or not 350.0 <= weight <= 650.0",
            mode="eval",
        ).body,
        include_attributes=False,
    )

    if not any(
        isinstance(node, ast.If)
        and ast.dump(
            node.test,
            include_attributes=False,
        ) == expected_range_condition
        for node in ast.walk(function)
    ):
        raise ValueError(
            "The existing 350–650 kg weight condition was not preserved."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Restrict the weight-distribution chart and its statistics "
            "to finishing positions 1, 2, and 3."
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
        print(
            f"The top-three weight-chart condition is already applied to: "
            f"{app_path}"
        )
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-chart-top-three-condition.bak"
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
    print("Weight chart now includes finishing positions 1, 2, and 3 only.")
    print("The 350–650 kg inclusive weight restriction is preserved.")
    print("Histogram and chart statistics use the same included records.")
    print("Existing filters and other summary metrics are unchanged.")
    print("Restart or redeploy the application, then reload the weight chart.")
    print("Interactive browser testing is still required.")


if __name__ == "__main__":
    main()
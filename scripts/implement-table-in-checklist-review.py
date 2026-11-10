# scripts/implement-table-in-checklist-review.py
#
# Updates the Checklist Review results table:
#   - Increases its visible height by 20%.
#   - Adds Trainer, Breeding Farm, and Stallion columns.
#
# If the table has no explicit height, sets it to 480 pixels
# using a 400-pixel baseline.
#
# Does not change:
#   - Filtering, pagination, or the number of records per page.
#   - Database records.
#   - Existing Arrow-compatible dataframe conversion.
#   - Charts, login, or filter history.
#
# Run:
#   python scripts/implement-table-in-checklist-review.py
#
# Or specify the application file:
#   python scripts/implement-table-in-checklist-review.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# REVIEW_TABLE_TALLER_AND_REFERENCE_COLUMNS_V1"

NEW_COLUMNS = [
    ("Trainer", "trainer_name"),
    ("Breeding Farm", "breeding_farm_name"),
    ("Stallion", "stallion_name"),
]


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


def is_named_call(node, name):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def add_reference_columns(summary_function):
    dictionaries = []

    for node in ast.walk(summary_function):
        if not isinstance(node, ast.Dict):
            continue

        keys = {
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        }

        if {"Horse", "Jockey"}.issubset(keys):
            dictionaries.append(node)

    if len(dictionaries) != 1:
        raise ValueError(
            "Could not uniquely identify the summary table's row dictionary."
        )

    row = dictionaries[0]

    existing_columns = {
        key.value
        for key in row.keys
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
    }

    jockey_position = next(
        index
        for index, key in enumerate(row.keys)
        if isinstance(key, ast.Constant)
        and key.value == "Jockey"
    )

    insertion_position = jockey_position + 1

    for label, field in NEW_COLUMNS:
        if label in existing_columns:
            continue

        row.keys.insert(
            insertion_position,
            ast.Constant(value=label),
        )

        row.values.insert(
            insertion_position,
            ast.parse(
                f"entry.get({field!r}) or ''",
                mode="eval",
            ).body,
        )

        insertion_position += 1


def increase_results_table_height(review_function):
    summary_variables = set()

    for node in ast.walk(review_function):
        if (
            isinstance(node, ast.Assign)
            and is_named_call(
                node.value,
                "build_summary_dataframe",
            )
        ):
            summary_variables.update(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            )

    if not summary_variables:
        raise ValueError(
            "Could not identify the review summary dataframe variable."
        )

    table_calls = []

    for node in ast.walk(review_function):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "dataframe"
        ):
            continue

        data_argument = node.args[0] if node.args else next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "data"
            ),
            None,
        )

        if (
            isinstance(data_argument, ast.Name)
            and data_argument.id in summary_variables
        ):
            table_calls.append(node)

    if len(table_calls) != 1:
        raise ValueError(
            "Could not uniquely identify the Checklist Review results table."
        )

    table = table_calls[0]

    heights = [
        keyword
        for keyword in table.keywords
        if keyword.arg == "height"
    ]

    if len(heights) > 1:
        raise ValueError("Unexpected duplicate table-height arguments.")

    if not heights:
        table.keywords.append(
            ast.keyword(
                arg="height",
                value=ast.Constant(value=480),
            )
        )
        return

    current_height = heights[0].value

    if (
        isinstance(current_height, ast.Constant)
        and type(current_height.value) in (int, float)
        and current_height.value > 0
    ):
        heights[0].value = ast.Constant(
            value=max(1, round(current_height.value * 1.2))
        )

    elif (
        isinstance(current_height, ast.Constant)
        and current_height.value in (None, "auto", "content")
    ):
        heights[0].value = ast.Constant(value=480)

    else:
        raise ValueError(
            "The results table uses a dynamic or unsupported height. "
            "No changes were applied."
        )


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    functions = {
        name: find_function(tree, name)
        for name in (
            "build_summary_dataframe",
            "render_checklist_review_page",
        )
    }

    spans = {
        name: (function.lineno - 1, function.end_lineno)
        for name, function in functions.items()
    }

    if any(
        function.decorator_list
        for function in functions.values()
    ):
        raise ValueError(
            "Unexpected decorators on the summary or review functions."
        )

    add_reference_columns(
        functions["build_summary_dataframe"]
    )

    increase_results_table_height(
        functions["render_checklist_review_page"]
    )

    lines = source.splitlines(keepends=True)
    edits = []

    for name, function in functions.items():
        ast.fix_missing_locations(function)

        replacement = ast.unparse(function) + "\n\n"

        if name == "build_summary_dataframe":
            replacement = PATCH_MARKER + "\n" + replacement

        start, end = spans[name]
        edits.append((start, end, replacement))

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<review-table-improvements>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    changed_functions = {
        "build_summary_dataframe",
        "render_checklist_review_page",
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in changed_functions
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the review table functions."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid table patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Increase Checklist Review table height by 20% and add "
            "Trainer, Breeding Farm, and Stallion columns."
        )
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
        print(f"The review table improvements are already applied: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-review-table-improvements.bak"
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
    print("Increased the results table height by 20%.")
    print("Tables without an explicit height now use 480 pixels.")
    print("Added Trainer, Breeding Farm, and Stallion columns.")
    print("Filtering, pagination, and stored records are unchanged.")
    print("Restart or redeploy the application to view the changes.")
    print("Desktop and mobile visual testing are still required.")


if __name__ == "__main__":
    main()
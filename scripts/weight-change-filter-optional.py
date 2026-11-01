# scripts/weight-change-filter-optional.py
#
# Applies the optional Weight Change filter changes to app.py.
#
# Run from the project root:
#     python scripts/weight-change-filter-optional.py
#
# Or specify another application file:
#     python scripts/weight-change-filter-optional.py path/to/app.py

import argparse
import ast
from pathlib import Path
import shutil


MARKER = "# Optional weight-change filtering enabled."


def patch_application(source):
    if MARKER in source:
        return source

    updated = source

    def replace_once(old, new):
        nonlocal updated

        count = updated.count(old)

        if count != 1:
            raise ValueError(
                "Cannot safely apply the patch. "
                f"Expected one occurrence, found {count}:\n{old}"
            )

        updated = updated.replace(old, new, 1)

    # Both the first and second filters use these defaults.
    replace_once(
        '        "weight_change_from": -999.9,',
        '        "enable_weight_change_filter": False,\n'
        '        "weight_change_from": -999.9,',
    )

    # Include the checkbox setting when saving the first filter.
    replace_once(
        '        "weight_change_from": get_value("weight_change_from", -999.9),',
        '        "enable_weight_change_filter": get_value(\n'
        '            "enable_weight_change_filter", False\n'
        '        ),\n'
        '        "weight_change_from": get_value("weight_change_from", -999.9),',
    )

    # Restore the checkbox when loading a saved filter.
    # Saved filters without this field default to disabled.
    replace_once(
        '    set_value(\n        "weight_change_from",',
        '    set_value(\n'
        '        "enable_weight_change_filter",\n'
        '        bool(filter_data.get("enable_weight_change_filter", False)),\n'
        '    )\n'
        '    set_value(\n        "weight_change_from",',
    )

    # Preserve zero-valued bounds when loading saved filters.
    replace_once(
        'float(filter_data.get("weight_change_from", -999.9) or -999.9)',
        'float(\n'
        '            filter_data.get("weight_change_from")\n'
        '            if filter_data.get("weight_change_from") is not None\n'
        '            else -999.9\n'
        '        )',
    )

    replace_once(
        'float(filter_data.get("weight_change_to", 999.9) or 999.9)',
        'float(\n'
        '            filter_data.get("weight_change_to")\n'
        '            if filter_data.get("weight_change_to") is not None\n'
        '            else 999.9\n'
        '        )',
    )

    # Add an optional argument at the end to preserve existing positional calls.
    replace_once(
        "    weight_to,\n):\n    filtered = []",
        "    weight_to,\n"
        "    enable_weight_change_filter=False,\n"
        "):\n"
        "    filtered = []",
    )

    # Only apply the weight-change range when its checkbox is checked.
    old_filter = '''        weight_change_value = entry.get("weight_change")

        if weight_change_value is None:
            if weight_change_from > -999.9 or weight_change_to < 999.9:
                continue
        elif (
            weight_change_value < weight_change_from
            or weight_change_value > weight_change_to
        ):
            continue
'''

    new_filter = '''        if enable_weight_change_filter:
            weight_change_value = entry.get("weight_change")

            if weight_change_value is None:
                continue

            if (
                weight_change_value < weight_change_from
                or weight_change_value > weight_change_to
            ):
                continue
'''

    replace_once(old_filter, new_filter)

    # Add separate checkboxes for the first and second review filters.
    configurations = [
        {
            "prefix": "filter_",
            "indent": "            ",
            "key_function": "saved_filter_key",
            "label": "Apply Weight Change Filter",
        },
        {
            "prefix": "second_filter_",
            "indent": "        ",
            "key_function": "second_filter_key",
            "label": "Apply Second Weight Change Filter",
        },
    ]

    for configuration in configurations:
        prefix = configuration["prefix"]
        indent = configuration["indent"]
        key_function = configuration["key_function"]
        label = configuration["label"]
        enabled_variable = f"{prefix}enable_weight_change_filter"

        input_start = (
            f"{indent}{prefix}weight_change_from = st.number_input("
        )

        checkbox = (
            f"{indent}{enabled_variable} = st.checkbox(\n"
            f'{indent}    "{label}",\n'
            f"{indent}    key={key_function}(\n"
            f'{indent}        owner_id, "enable_weight_change_filter"\n'
            f"{indent}    ),\n"
            f"{indent}    help=(\n"
            f'{indent}        "Check to apply the From/To weight-change range. "\n'
            f'{indent}        "Unchecked means weight change is ignored."\n'
            f"{indent}    ),\n"
            f"{indent})\n\n"
        )

        replace_once(input_start, checkbox + input_start)

        # Keep the range values, but disable editing when the filter is off.
        for bound in ("from", "to"):
            key_line = (
                f"{indent}    key={key_function}"
                f'(owner_id, "weight_change_{bound}"),'
            )

            replace_once(
                key_line,
                key_line
                + f"\n{indent}    disabled=not {enabled_variable},",
            )

        # Pass the checkbox setting into the shared filtering function.
        call_argument = (
            f"        weight_change_from={prefix}weight_change_from,"
        )

        replace_once(
            call_argument,
            f"        enable_weight_change_filter={enabled_variable},\n"
            + call_argument,
        )

    updated += f"\n\n{MARKER}\n"

    ast.parse(updated)

    return updated


def test_filter_logic(source):
    import inspect
    import json
    from datetime import date, datetime

    import pandas as pd

    tree = ast.parse(source)

    required_functions = {
        "clean_text",
        "parse_race_date",
        "filter_checklists",
    }

    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in required_functions
    ]

    found = {node.name for node in function_nodes}

    if found != required_functions:
        raise ValueError(
            f"Missing functions required for validation: "
            f"{required_functions - found}"
        )

    namespace = {
        "pd": pd,
        "json": json,
        "date": date,
        "datetime": datetime,
    }

    test_module = ast.Module(
        body=function_nodes,
        type_ignores=[],
    )

    exec(
        compile(test_module, "<weight-change-filter-tests>", "exec"),
        namespace,
    )

    filter_function = namespace["filter_checklists"]

    arguments = {
        name: 0
        for name in inspect.signature(filter_function).parameters
    }

    arguments.update(
        checklists=[
            {"weight_change": None},
            {"weight_change": -10.0},
            {"weight_change": 0.0},
            {"weight_change": 4.0},
            {"weight_change": 20.0},
        ],
        selected_filters={},
        selected_venue_ids=[],
        criteria_filters=[],
        criteria_mode="AND",
        distance_from=0,
        distance_to=5000,
        previous_distance_from=0,
        previous_distance_to=5000,
        interval_days_from=0,
        interval_days_to=9999,
        weight_change_from=0.0,
        weight_change_to=4.0,
        date_from=None,
        date_to=None,
        memo_keyword="",
        program_number=0,
        number_of_horses=0,
        finished_places=[],
        exclude_finished_places=[],
        odds_from=0.0,
        odds_to=999.9,
        prize_from=0.0,
        prize_to=1_000_000_000.0,
        enable_bracket_filter=False,
        bracket_from=1,
        bracket_to=8,
        enable_horse_filter=False,
        horse_from=1,
        horse_to=18,
        enable_weight_filter=False,
        weight_from=0.0,
        weight_to=999.9,
        enable_weight_change_filter=False,
    )

    result = filter_function(**arguments)

    if len(result) != 5:
        raise AssertionError(
            "Unchecked filter must retain all weight-change values, "
            "including missing values."
        )

    arguments["enable_weight_change_filter"] = True

    result = filter_function(**arguments)

    if [entry["weight_change"] for entry in result] != [0.0, 4.0]:
        raise AssertionError(
            "Checked filter must apply inclusive bounds "
            "and exclude missing values."
        )

    arguments["weight_change_from"] = 5.0

    if filter_function(**arguments):
        raise AssertionError(
            "A reversed weight-change range must return no results."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Make Checklist Review weight-change filtering optional "
            "and apply the changes to the application."
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

    if MARKER in source:
        print("The optional weight-change filter patch is already applied.")
        return

    try:
        updated = patch_application(source)
        test_filter_logic(updated)
    except Exception as error:
        raise SystemExit(
            f"Patch validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-weight-change-filter.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before running this patch."
        )

    shutil.copy2(app_path, backup_path)

    try:
        app_path.write_text(updated, encoding="utf-8")
    except Exception:
        shutil.copy2(backup_path, app_path)
        raise

    print(f"Updated application: {app_path}")
    print(f"Original application backup: {backup_path}")
    print("Syntax validation and three filter-logic tests passed.")
    print(
        "Weight-change filtering is now applied only when "
        "its checkbox is checked."
    )


if __name__ == "__main__":
    main()
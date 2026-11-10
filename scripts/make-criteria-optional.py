# scripts/make-criteria-optional.py
#
# Makes these Checklist Review filters optional:
#   - Distance
#   - Previous Distance
#   - Days Since Last Race
#
# Each range has its own checkbox, unchecked by default.
#
# Unchecked:
#   - From/To inputs are disabled.
#   - The criterion does not affect the results.
#
# Checked:
#   - From/To inputs are enabled.
#   - The inclusive range is applied.
#   - Records missing the corresponding value are excluded.
#
# Applies to both first-filter and second-filter controls.
# Saved filters preserve the checkbox settings.
# Older saved filters default to these criteria being disabled.
# Existing filter history includes the new flags through get_filter_defaults().
#
# Run:
#   python scripts/make-criteria-optional.py
#
# Or specify the application file:
#   python scripts/make-criteria-optional.py app.py
#
# This version fixes the duplicate distance_value assignment issue.
# No sample data or additional database queries are used.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# OPTIONAL_DISTANCE_AND_INTERVAL_FILTERS_V1"

FILTERS = {
    "distance": {
        "flag": "enable_distance_filter",
        "label": "Apply Distance Filter",
        "variable": "distance_value",
    },
    "previous_distance": {
        "flag": "enable_previous_distance_filter",
        "label": "Apply Previous Distance Filter",
        "variable": "previous_distance_value",
    },
    "interval_days": {
        "flag": "enable_interval_days_filter",
        "label": "Apply Days Since Last Race Filter",
        "variable": "interval_days_value",
    },
}


def parse_expression(text):
    return ast.parse(text, mode="eval").body


def expression_matches(left, right):
    return ast.dump(
        left,
        include_attributes=False,
    ) == ast.dump(
        right,
        include_attributes=False,
    )


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


def assignment_to(node, name):
    return (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == name
            for target in node.targets
        )
    )


def dictionary_contains(dictionary, key_name):
    return any(
        isinstance(key, ast.Constant)
        and key.value == key_name
        for key in dictionary.keys
    )


def find_return_dictionary(function, description):
    matches = [
        statement.value
        for statement in function.body
        if (
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Dict)
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Could not uniquely identify the {description} dictionary."
        )

    return matches[0]


def add_default_flags(function):
    dictionary = find_return_dictionary(
        function,
        "filter-default",
    )

    for configuration in FILTERS.values():
        flag = configuration["flag"]

        if dictionary_contains(dictionary, flag):
            raise ValueError(
                f"The filter default already contains {flag} "
                "without the expected patch marker."
            )

        dictionary.keys.append(ast.Constant(value=flag))
        dictionary.values.append(ast.Constant(value=False))


def add_saved_filter_flags(function):
    dictionary = find_return_dictionary(
        function,
        "saved-filter",
    )

    for configuration in FILTERS.values():
        flag = configuration["flag"]

        if dictionary_contains(dictionary, flag):
            raise ValueError(
                f"The saved-filter dictionary already contains {flag} "
                "without the expected patch marker."
            )

        dictionary.keys.append(ast.Constant(value=flag))
        dictionary.values.append(
            parse_expression(f'get_value("{flag}", False)')
        )


def add_saved_filter_loading(function):
    # The existing function defines a local set_value() helper.
    local_helpers = [
        statement
        for statement in function.body
        if isinstance(statement, ast.FunctionDef)
        and statement.name == "set_value"
    ]

    if len(local_helpers) != 1:
        raise ValueError(
            "Could not identify the saved-filter set_value() helper."
        )

    statements = []

    for configuration in FILTERS.values():
        flag = configuration["flag"]

        statements.extend(
            ast.parse(
                f'set_value("{flag}", '
                f'bool(filter_data.get("{flag}", False)))'
            ).body
        )

    # Insert immediately after the local helper definition so flags
    # are restored before the rest of the saved-filter values.
    helper_position = function.body.index(local_helpers[0])
    function.body[helper_position + 1:helper_position + 1] = statements


def update_filter_logic(function):
    existing_arguments = {
        argument.arg
        for argument in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
        )
    }

    for configuration in FILTERS.values():
        flag = configuration["flag"]

        if flag in existing_arguments:
            raise ValueError(
                f"The filter function already contains {flag} "
                "without the expected patch marker."
            )

        function.args.args.append(ast.arg(arg=flag))
        function.args.defaults.append(ast.Constant(value=False))
        existing_arguments.add(flag)

    loops = [
        statement
        for statement in function.body
        if (
            isinstance(statement, ast.For)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "entry"
            and isinstance(statement.iter, ast.Name)
            and statement.iter.id == "checklists"
        )
    ]

    if len(loops) != 1:
        raise ValueError(
            "Could not uniquely identify the checklist filtering loop."
        )

    loop = loops[0]

    for field_name, configuration in FILTERS.items():
        variable = configuration["variable"]

        # Match the direct entry lookup, not the later assignment
        # that normalizes distance_value.
        expected_lookup = parse_expression(
            f"entry.get({field_name!r})"
        )

        positions = [
            index
            for index, statement in enumerate(loop.body)
            if (
                assignment_to(statement, variable)
                and expression_matches(
                    statement.value,
                    expected_lookup,
                )
            )
        ]

        if len(positions) != 1:
            raise ValueError(
                "Could not uniquely identify the source lookup for "
                f"{field_name}."
            )

        start = positions[0]

        if field_name == "distance":
            block_length = 3
            block = loop.body[start:start + block_length]

            if not (
                len(block) == block_length
                and assignment_to(block[1], variable)
                and isinstance(block[2], ast.If)
            ):
                raise ValueError(
                    "Unexpected Distance filter structure."
                )

            expected_normalization = parse_expression(
                f"{variable} if {variable} is not None else 0"
            )

            if not expression_matches(
                block[1].value,
                expected_normalization,
            ):
                raise ValueError(
                    "Unexpected Distance missing-value normalization."
                )

            range_condition = block[2].test

        else:
            block_length = 2
            block = loop.body[start:start + block_length]

            if not (
                len(block) == block_length
                and isinstance(block[1], ast.If)
                and expression_matches(
                    block[1].test,
                    parse_expression(f"{variable} is None"),
                )
                and len(block[1].orelse) == 1
                and isinstance(block[1].orelse[0], ast.If)
            ):
                raise ValueError(
                    f"Unexpected filter structure for {field_name}."
                )

            range_condition = block[1].orelse[0].test

        expected_range_condition = parse_expression(
            f"{variable} < {field_name}_from "
            f"or {variable} > {field_name}_to"
        )

        if not expression_matches(
            range_condition,
            expected_range_condition,
        ):
            raise ValueError(
                f"Unexpected range comparison for {field_name}."
            )

        replacement = ast.If(
            test=ast.Name(
                id=configuration["flag"],
                ctx=ast.Load(),
            ),
            body=[
                block[0],
                ast.If(
                    test=parse_expression(
                        f"{variable} is None"
                    ),
                    body=[ast.Continue()],
                    orelse=[],
                ),
                ast.If(
                    test=range_condition,
                    body=[ast.Continue()],
                    orelse=[],
                ),
            ],
            orelse=[],
        )

        loop.body[start:start + block_length] = [replacement]


class UpdateFilterUI(ast.NodeTransformer):
    def __init__(self, key_function, second=False):
        self.key_function = key_function
        self.second = second
        self.updated_fields = {}
        self.checkbox_count = 0
        self.filter_call_count = 0

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        call = node.value

        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "number_input"
        ):
            return node

        key_calls = [
            keyword.value
            for keyword in call.keywords
            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id == self.key_function
            )
        ]

        if len(key_calls) != 1:
            return node

        key_call = key_calls[0]

        if not (
            len(key_call.args) >= 2
            and isinstance(key_call.args[1], ast.Constant)
            and isinstance(key_call.args[1].value, str)
        ):
            return node

        field = key_call.args[1].value

        for prefix, configuration in FILTERS.items():
            if field not in (
                f"{prefix}_from",
                f"{prefix}_to",
            ):
                continue

            flag = configuration["flag"]
            state_key = (
                f'{self.key_function}(owner_id, "{flag}")'
            )

            call.keywords = [
                keyword
                for keyword in call.keywords
                if keyword.arg != "disabled"
            ]

            call.keywords.append(
                ast.keyword(
                    arg="disabled",
                    value=parse_expression(
                        f"not st.session_state.get({state_key}, False)"
                    ),
                )
            )

            self.updated_fields[field] = (
                self.updated_fields.get(field, 0) + 1
            )

            if field.endswith("_from"):
                label = configuration["label"]

                if self.second:
                    label = "Second Filter: " + label

                checkbox = ast.parse(
                    f"st.checkbox({label!r}, key={state_key})"
                ).body[0]

                self.checkbox_count += 1
                return [checkbox, node]

            return node

        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)

        if not (
            isinstance(node.func, ast.Name)
            and node.func.id == "filter_checklists"
        ):
            return node

        self.filter_call_count += 1

        existing_keywords = {
            keyword.arg
            for keyword in node.keywords
            if keyword.arg is not None
        }

        for configuration in FILTERS.values():
            flag = configuration["flag"]

            if flag in existing_keywords:
                raise ValueError(
                    f"The filtering call already contains {flag}."
                )

            node.keywords.append(
                ast.keyword(
                    arg=flag,
                    value=parse_expression(
                        "st.session_state.get("
                        f'{self.key_function}(owner_id, "{flag}"), '
                        "False)"
                    ),
                )
            )

        return node


def validate_patch_scope(original, updated, changed_functions):
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
            "Unexpected changes outside the intended filter functions."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid optional-filter patch marker.")


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    function_names = [
        "get_filter_defaults",
        "collect_current_filter_data",
        "apply_saved_filter_to_session",
        "filter_checklists",
        "render_checklist_review_page",
        "render_second_filter_section",
    ]

    functions = {
        name: find_function(tree, name)
        for name in function_names
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
            "Unexpected decorators on the filter functions."
        )

    add_default_flags(
        functions["get_filter_defaults"]
    )

    add_saved_filter_flags(
        functions["collect_current_filter_data"]
    )

    add_saved_filter_loading(
        functions["apply_saved_filter_to_session"]
    )

    update_filter_logic(
        functions["filter_checklists"]
    )

    expected_fields = {
        f"{prefix}_{bound}"
        for prefix in FILTERS
        for bound in ("from", "to")
    }

    for function_name, key_function, second in (
        (
            "render_checklist_review_page",
            "saved_filter_key",
            False,
        ),
        (
            "render_second_filter_section",
            "second_filter_key",
            True,
        ),
    ):
        transformer = UpdateFilterUI(
            key_function=key_function,
            second=second,
        )

        functions[function_name] = transformer.visit(
            functions[function_name]
        )

        if (
            set(transformer.updated_fields) != expected_fields
            or any(
                count != 1
                for count in transformer.updated_fields.values()
            )
        ):
            missing = sorted(
                expected_fields - set(transformer.updated_fields)
            )

            raise ValueError(
                f"Could not uniquely update every range input in "
                f"{function_name}. Missing fields: {missing}"
            )

        if transformer.checkbox_count != len(FILTERS):
            raise ValueError(
                f"Expected three optional-filter checkboxes in "
                f"{function_name}."
            )

        if transformer.filter_call_count != 1:
            raise ValueError(
                f"Expected exactly one filter_checklists() call in "
                f"{function_name}."
            )

    lines = source.splitlines(keepends=True)
    edits = []

    for name, function in functions.items():
        ast.fix_missing_locations(function)
        start, end = spans[name]

        replacement = ast.unparse(function) + "\n\n"

        if name == "get_filter_defaults":
            replacement = (
                PATCH_MARKER + "\n" + replacement
            )

        edits.append(
            (start, end, replacement)
        )

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(
        updated,
        "<optional-distance-and-interval-filters>",
        "exec",
    )

    validate_patch_scope(
        source,
        updated,
        set(function_names),
    )

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Make Distance, Previous Distance, and Days Since Last Race "
            "optional checkbox-controlled filters in Checklist Review."
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
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    source = app_path.read_text(
        encoding="utf-8-sig"
    )

    if PATCH_MARKER in source:
        print(
            f"The optional criteria feature is already applied to: "
            f"{app_path}"
        )
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-optional-distance-interval-filters.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(
        app_path,
        backup_path,
    )

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
            temporary_path = Path(
                temporary_file.name
            )
            temporary_file.write(
                updated
            )

        shutil.copymode(
            app_path,
            temporary_path,
        )

        temporary_path.replace(
            app_path
        )

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Backup: {backup_path}")
    print("Python syntax and patch-scope validation passed.")
    print("Added optional checkboxes for:")
    print("  - Distance")
    print("  - Previous Distance")
    print("  - Days Since Last Race")
    print("Each checkbox defaults to unchecked.")
    print("Unchecked criteria do not affect results.")
    print("Checked criteria apply inclusive From/To ranges.")
    print("Both first-filter and second-filter controls were updated.")
    print("Saved filters preserve the checkbox settings.")
    print("Existing filter history captures the new settings.")
    print("Restart or redeploy the app, then reload Checklist Review.")
    print("Interactive filtering and history testing are still required.")


if __name__ == "__main__":
    main()
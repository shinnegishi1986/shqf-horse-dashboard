# scripts/accept-input-even-though-the-data-is-not-registered.py
#
# Allows new names to be entered directly on the Race Checklist page.
#
# Existing registered names remain available as suggestions.
# New names are registered automatically when Save Checklist is pressed.
#
# Applies to:
#   - Horse
#   - Horse owner
#   - Jockey
#   - Previous jockey
#   - Trainer
#   - Breeding farm
#   - Stallion
#   - Broodmare sire
#   - Venue
#   - Previous venue
#   - Race name
#
# Existing names are reused using the application's case-insensitive lookup.
# Merely typing a name does not register it; registration happens on save.
#
# Streamlit versions supporting accept_new_options use one selectbox for
# suggestions and new input. Older versions show a separate new-name input.
#
# Run:
#   python scripts/accept-input-even-though-the-data-is-not-registered.py
#
# Or specify the application file:
#   python scripts/accept-input-even-though-the-data-is-not-registered.py app.py
#
# Note:
#   The existing application saves reference names separately from checklists.
#   If checklist saving fails afterward, newly registered names can remain.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# RACE_CHECKLIST_ACCEPT_NEW_REFERENCE_NAMES_V1"


# Existing selectbox variable -> (reference type, existing option list).
FIELD_CONFIG = {
    "selected_horse_idx": ("horse", "horse_options"),
    "selected_horse_owner_idx": ("horse_owner", "horse_owner_options"),
    "selected_jockey_idx": ("jockey", "jockey_options"),
    "selected_previous_jockey_idx": ("jockey", "jockey_options"),
    "selected_trainer_idx": ("trainer", "trainer_options"),
    "selected_breeding_farm_idx": ("breeding_farm", "breeding_farm_options"),
    "selected_stallion_idx": ("stallion", "stallion_options"),
    "selected_broodmare_sire_idx": ("stallion", "stallion_options"),
    "selected_venue_idx": ("venue", "venue_options"),
    "selected_previous_venue_idx": ("venue", "venue_options"),
    "selected_race_idx": ("race_name", "race_options"),
}


HELPERS = r'''
# RACE_CHECKLIST_ACCEPT_NEW_REFERENCE_NAMES_V1
def render_race_reference_input(label, existing_options, key):
    import inspect

    # make_options() puts "(No selection)" at index zero.
    names = [
        clean_text(value)
        for value in existing_options[1:]
        if clean_text(value)
    ]

    try:
        supports_new_options = (
            "accept_new_options"
            in inspect.signature(st.selectbox).parameters
        )
    except (TypeError, ValueError):
        supports_new_options = False

    if supports_new_options:
        selected_name = st.selectbox(
            label,
            options=names,
            index=None,
            key=key,
            accept_new_options=True,
            placeholder="Select a registered name or type a new name",
            help=(
                "Registered names remain available as suggestions. "
                "A new name is registered when you save the checklist."
            ),
        )

        return clean_text(selected_name)

    selected_name = st.selectbox(
        label,
        options=[None] + names,
        index=0,
        format_func=lambda value: (
            value if value is not None else "(No selection)"
        ),
        key=key,
    )

    new_name = st.text_input(
        f"New name for {label}",
        key=f"{key}_new_name",
        help=(
            "Optional. Enter a name that is not listed above. "
            "If entered, this name takes priority over the selected name."
        ),
    )

    return clean_text(new_name) or clean_text(selected_name)


def resolve_race_reference_input(template_type, owner_id, value):
    name = clean_text(value)

    if not name:
        return None

    item_id = find_or_create_template_item(
        template_type,
        owner_id,
        name,
    )

    if item_id is None:
        raise ValueError(
            f"Could not register or find {template_type.replace('_', ' ')}: "
            f"{name}. Please try again."
        )

    return item_id

'''


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


class UpdateRaceChecklist(ast.NodeTransformer):
    def __init__(self):
        self.updated_inputs = set()
        self.updated_resolvers = set()
        self.updated_save_calls = 0

    def visit_Assign(self, node):
        # Replace only the known reference-name selectboxes.
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in FIELD_CONFIG
        ):
            variable = node.targets[0].id
            value = node.value

            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "st"
                and value.func.attr == "selectbox"
                and value.args
            ):
                raise ValueError(
                    f"Unexpected selector structure for {variable}."
                )

            keys = [
                keyword.value
                for keyword in value.keywords
                if keyword.arg == "key"
            ]

            if len(keys) != 1:
                raise ValueError(
                    f"Could not identify the widget key for {variable}."
                )

            _, options_name = FIELD_CONFIG[variable]

            # A new key avoids reusing the previous integer-index state.
            new_key = ast.BinOp(
                left=keys[0],
                op=ast.Add(),
                right=ast.Constant(value="_accept_name"),
            )

            node.value = ast.Call(
                func=ast.Name(
                    id="render_race_reference_input",
                    ctx=ast.Load(),
                ),
                args=[
                    value.args[0],
                    ast.Name(id=options_name, ctx=ast.Load()),
                ],
                keywords=[
                    ast.keyword(arg="key", value=new_key),
                ],
            )

            self.updated_inputs.add(variable)
            return node

        node = self.generic_visit(node)

        # Catch reference-registration failures at the existing save call.
        if is_named_call(node.value, "add_checklist"):
            self.updated_save_calls += 1

            validation = ast.parse(
                '''
if not normalized_date_of_race:
    st.error("Date of race is required.")
    return
'''
            ).body

            protected_save = ast.Try(
                body=[node],
                handlers=[
                    ast.ExceptHandler(
                        type=ast.Name(id="ValueError", ctx=ast.Load()),
                        name="reference_error",
                        body=ast.parse(
                            '''
st.error(str(reference_error))
return
'''
                        ).body,
                    )
                ],
                orelse=[],
                finalbody=[],
            )

            return validation + [protected_save]

        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)

        if not is_named_call(node, "get_selected_id"):
            return node

        if len(node.args) != 2:
            return node

        selected = node.args[1]

        if not (
            isinstance(selected, ast.Name)
            and selected.id in FIELD_CONFIG
        ):
            return node

        template_type, _ = FIELD_CONFIG[selected.id]
        self.updated_resolvers.add(selected.id)

        return ast.copy_location(
            ast.Call(
                func=ast.Name(
                    id="resolve_race_reference_input",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Constant(value=template_type),
                    ast.Name(id="owner_id", ctx=ast.Load()),
                    selected,
                ],
                keywords=[],
            ),
            node,
        )


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    for required in (
        "clean_text",
        "find_or_create_template_item",
        "render_race_checklist_page",
    ):
        find_function(tree, required)

    for helper_name in (
        "render_race_reference_input",
        "resolve_race_reference_input",
    ):
        if any(
            isinstance(node, ast.FunctionDef)
            and node.name == helper_name
            for node in tree.body
        ):
            raise ValueError(
                f"Unexpected existing helper: {helper_name}"
            )

    race_page = find_function(tree, "render_race_checklist_page")

    if race_page.decorator_list:
        raise ValueError(
            "Unexpected decorators on render_race_checklist_page."
        )

    start_line = race_page.lineno - 1
    end_line = race_page.end_lineno

    transformer = UpdateRaceChecklist()
    updated_function = transformer.visit(race_page)
    ast.fix_missing_locations(updated_function)

    expected_fields = set(FIELD_CONFIG)

    if transformer.updated_inputs != expected_fields:
        raise ValueError(
            "Could not update every reference input. Missing: "
            f"{sorted(expected_fields - transformer.updated_inputs)}"
        )

    if transformer.updated_resolvers != expected_fields:
        raise ValueError(
            "Could not update every save-time reference lookup. Missing: "
            f"{sorted(expected_fields - transformer.updated_resolvers)}"
        )

    if transformer.updated_save_calls != 1:
        raise ValueError(
            "Expected exactly one checklist save call."
        )

    lines = source.splitlines(keepends=True)

    updated = (
        "".join(lines[:start_line])
        + HELPERS.strip("\n")
        + "\n\n"
        + ast.unparse(updated_function)
        + "\n\n"
        + "".join(lines[end_line:])
    )

    compile(updated, "<accept-new-reference-names>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    ignored_functions = {
        "render_race_checklist_page",
        "render_race_reference_input",
        "resolve_race_reference_input",
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in ignored_functions
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the Race Checklist page "
            "and its new reference-input helpers."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("The patch marker is invalid.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Allow new reference names to be entered and registered "
            "directly when saving a Race Checklist."
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
        print(f"This feature is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-accept-new-reference-names.bak"
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
    print("Existing registered names remain available as suggestions.")
    print("New names are registered when Save Checklist is pressed.")
    print("Existing names are reused where a matching name is found.")
    print("Checklist Review and other application features were preserved.")
    print("Restart or redeploy the application, then reload Race Checklist.")
    print("Interactive Streamlit testing is still required.")


if __name__ == "__main__":
    main()
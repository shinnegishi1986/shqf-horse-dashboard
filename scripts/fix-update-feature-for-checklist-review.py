# scripts/fix-update-feature-for-checklist-review.py
#
# Replaces the extra "New name" text inputs with one editable
# suggestion selector per Checklist Review reference field.
#
# User interaction:
#   1. Select an existing suggestion OR type a new name.
#   2. Press Enter to accept the typed name.
#   3. Click Update Checklist to save.
#
# No additional "New name" inputs are displayed.
#
# Requires the preceding:
#   scripts/implement-update-feature-for-checklist-review.py
#
# Preserves its transactional reference-registration logic.
# Compatible with Race Class and template loading.
#
# Native Streamlit selectbox accept_new_options support is required.
# Older versions show an upgrade instruction, not extra inputs.
#
# Stop Streamlit before running:
#
# python scripts/fix-update-feature-for-checklist-review.py app.py

RUNTIME = r'''
# CHECKLIST_REVIEW_SINGLE_REFERENCE_INPUT_V1

def _crf_key(owner_id, entry_id, field):
    return f"crf_reference_{owner_id}_{entry_id}_{field}"


def _crf_require_native():
    import inspect

    try:
        supported = (
            "accept_new_options"
            in inspect.signature(st.selectbox).parameters
        )
    except (TypeError, ValueError):
        supported = False

    if not supported:
        st.error(
            "This editor requires a Streamlit version supporting "
            "selectbox accept_new_options. Upgrade Streamlit "
            "and restart: "
            "python -m pip install --upgrade streamlit"
        )
        st.stop()


def _crf_reference(
    label,
    owner_id,
    entry_id,
    field,
    labels,
    ids,
    current_id,
    return_id=False,
):
    options = [None]

    for item_id, name in zip(ids, labels):
        if item_id is not None:
            name = str(name).strip()

            if name and name not in options:
                options.append(name)

    current_name = next(
        (
            str(name).strip()
            for item_id, name in zip(ids, labels)
            if item_id == current_id
            and item_id is not None
        ),
        None,
    )

    if current_name not in options:
        current_name = None

    key = _crf_key(
        owner_id,
        entry_id,
        field,
    )

    selected = st.selectbox(
        label,
        options=options,
        index=(
            None
            if key in st.session_state
            else options.index(current_name)
        ),
        format_func=lambda value: (
            "(No selection)"
            if value is None
            else value
        ),
        key=key,
        accept_new_options=True,
        placeholder=(
            "Select an existing name or type a new name"
        ),
        help=(
            "Select a suggestion, or type a new name "
            "and press Enter. New names are registered "
            "only when Update Checklist succeeds."
        ),
    )

    if selected is None or not str(selected).strip():
        return (
            None if return_id else 0
        ), ""

    name = str(selected).strip()

    exact = [
        (index, item_id)
        for index, (item_id, label_value)
        in enumerate(zip(ids, labels))
        if item_id is not None
        and str(label_value).strip() == name
    ]

    matching = exact or [
        (index, item_id)
        for index, (item_id, label_value)
        in enumerate(zip(ids, labels))
        if item_id is not None
        and str(label_value).strip().casefold()
        == name.casefold()
    ]

    if matching:
        # Preserve the current ID when duplicate display names exist.
        index, item_id = next(
            (
                pair
                for pair in matching
                if pair[1] == current_id
            ),
            matching[0],
        )

        return (
            item_id if return_id else index
        ), ""

    # A new name is passed to the existing transactional resolver.
    # No reference record is created while rendering the widget.
    return (
        None if return_id else 0
    ), name


def _crf_class(owner_id, entry):
    ids, labels = _rf_class_options(owner_id)

    return _crf_reference(
        "Race Class",
        owner_id,
        entry["id"],
        "race_class_id",
        labels,
        ids,
        entry.get("race_class_id"),
        return_id=True,
    )


def _crf_from_template(owner_id, entry_id, values):
    # The existing template callback supplies indexes.
    # Convert those to names for the new string-valued selectors.
    for widget, field, getter, name_column in (
        (
            "edit_race_idx",
            "race_name_id",
            get_user_race_names,
            "race_name",
        ),
        (
            "edit_venue_idx",
            "venue_id",
            get_user_venues,
            "venue_name",
        ),
    ):
        if widget in values:
            names = [None] + [
                str(row[name_column]).strip()
                for row in getter(owner_id)
            ]

            index = values[widget]

            if (
                not isinstance(index, int)
                or not 0 <= index < len(names)
            ):
                raise ValueError(
                    "The template selection is unavailable. "
                    "Reload the template."
                )

            st.session_state[
                _crf_key(owner_id, entry_id, field)
            ] = names[index]

    class_id = st.session_state.get(
        f"rf_editor_class_{owner_id}_{entry_id}"
    )

    if class_id is None:
        class_name = None

    else:
        rows = _rf_rows(
            "SELECT race_class_name FROM race_classes "
            "WHERE owner_id=? AND id=?",
            (owner_id, class_id),
        )

        if not rows:
            raise ValueError(
                "The template's race class is unavailable."
            )

        class_name = rows[0]["race_class_name"]

    st.session_state[
        _crf_key(owner_id, entry_id, "race_class_id")
    ] = class_name

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# CHECKLIST_REVIEW_SINGLE_REFERENCE_INPUT_V1"

SPECS = [
    (
        "edit_horse_idx",
        "horse_id",
        "Horse",
        "horse_options",
        "horse_ids",
    ),
    (
        "edit_horse_owner_idx",
        "horse_owner_id",
        "Horse Owner",
        "horse_owner_options",
        "horse_owner_ids",
    ),
    (
        "edit_jockey_idx",
        "jockey_id",
        "Jockey",
        "jockey_options",
        "jockey_ids",
    ),
    (
        "edit_previous_jockey_idx",
        "previous_jockey_id",
        "Previous Jockey",
        "jockey_options",
        "jockey_ids",
    ),
    (
        "edit_trainer_idx",
        "trainer_id",
        "Trainer",
        "trainer_options",
        "trainer_ids",
    ),
    (
        "edit_breeding_farm_idx",
        "breeding_farm_id",
        "Breeding Farm",
        "breeding_farm_options",
        "breeding_farm_ids",
    ),
    (
        "edit_stallion_idx",
        "stallion_id",
        "Stallion",
        "stallion_options",
        "stallion_ids",
    ),
    (
        "edit_broodmare_sire_idx",
        "broodmare_sire_id",
        "Broodmare Sire",
        "stallion_options",
        "stallion_ids",
    ),
    (
        "edit_venue_idx",
        "venue_id",
        "Venue",
        "venue_options",
        "venue_ids",
    ),
    (
        "edit_previous_venue_idx",
        "previous_venue_id",
        "Previous Venue",
        "venue_options",
        "venue_ids",
    ),
    (
        "edit_race_idx",
        "race_name_id",
        "Race Name",
        "race_options",
        "race_ids",
    ),
]


def find_function(tree, name):
    rows = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(rows) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(rows)}."
        )

    return rows[0]


def assignment_names(node):
    if not isinstance(node, ast.Assign):
        return set()

    return {
        item.id
        for target in node.targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name)
    }


def definition_start(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


class ReplaceInputs(ast.NodeTransformer):
    def __init__(self, specs):
        self.specs = {
            row[0]: row[1:]
            for row in specs
        }

        self.fields = {
            row[1]
            for row in specs
        }

        self.widgets = set()
        self.removed = set()
        self.prepares = 0

    def visit_FunctionDef(self, node):
        return node

    def visit_Assign(self, node):
        names = assignment_names(node)
        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_cru_input"
        ):
            expected = {
                "cru_new_" + field
                for field in self.fields
            }

            if (
                len(names) != 1
                or not names.issubset(expected)
            ):
                raise ValueError(
                    "Unexpected extra new-name input assignment."
                )

            field = next(iter(names))[
                len("cru_new_"):
            ]

            if field in self.removed:
                raise ValueError(
                    "Duplicate new-name input assignment."
                )

            self.removed.add(field)

            # Remove the separate text input completely.
            return None

        matches = names.intersection(
            self.specs
        )

        if not matches:
            return self.generic_visit(node)

        if len(matches) != 1:
            raise ValueError(
                "Ambiguous reference selector assignment."
            )

        widget = next(iter(matches))
        field, label, labels, ids = self.specs[widget]

        if field in self.widgets:
            raise ValueError(
                "Duplicate reference selector assignment."
            )

        self.widgets.add(field)

        if field == "race_class_id":
            expression = (
                "_crf_class(owner_id, entry)"
            )

        else:
            expression = (
                f"_crf_reference("
                f"{label!r}, owner_id, entry['id'], "
                f"{field!r}, {labels}, {ids}, "
                f"entry.get({field!r}))"
            )

        # The widget returns both:
        #   - the existing index/ID, if selected
        #   - a new-name string, if typed
        #
        # The existing transactional save mapping remains intact.
        return ast.parse(
            f"{widget}, cru_new_{field} = {expression}"
        ).body[0]

    def visit_Call(self, node):
        self.generic_visit(node)

        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "_cru_prepare"
        ):
            if len(node.args) != 3:
                raise ValueError(
                    "Unexpected editor state preparation call."
                )

            node.args[2] = ast.List(
                elts=[
                    ast.parse(
                        "_crf_key("
                        "owner_id, entry['id'], "
                        f"{field!r})",
                        mode="eval",
                    ).body
                    for field in sorted(self.fields)
                ],
                ctx=ast.Load(),
            )

            self.prepares += 1

        return node


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    editor = find_function(
        tree,
        "render_checklist_editor",
    )

    update = find_function(
        tree,
        "update_checklist",
    )

    find_function(tree, "_cru_resolve")
    find_function(tree, "_cru_prepare")

    old_input = find_function(
        tree,
        "_cru_input",
    )

    clear = find_function(
        tree,
        "_cru_clear_for_template",
    )

    if "_review_new_references" not in {
        argument.arg
        for argument in update.args.kwonlyargs
    }:
        raise ValueError(
            "Install the preceding Checklist Review "
            "update-feature script first."
        )

    helpers = {
        node.name
        for node in ast.parse(RUNTIME).body
        if isinstance(node, ast.FunctionDef)
    }

    existing = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    if helpers & existing:
        raise ValueError(
            "Conflicting single-input helper names "
            "already exist."
        )

    specs = list(SPECS)

    if "race_class_id" in {
        argument.arg
        for argument in (
            update.args.args
            + update.args.kwonlyargs
        )
    }:
        specs.append(
            (
                "rf_editor_class_id",
                "race_class_id",
                "Race Class",
                "",
                "",
            )
        )

    fields = {
        row[1]
        for row in specs
    }

    visitor = ReplaceInputs(specs)
    body = []

    for statement in editor.body:
        result = visitor.visit(statement)

        if result is not None:
            body.extend(
                result
                if isinstance(result, list)
                else [result]
            )

    editor.body = (
        ast.parse(
            "_crf_require_native()"
        ).body
        + body
    )

    if (
        visitor.widgets != fields
        or visitor.removed != fields
        or visitor.prepares != 1
    ):
        raise ValueError(
            "Cannot safely identify all previous selectors, "
            "extra inputs, and state preparation."
        )

    saves = [
        node
        for node in ast.walk(editor)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update_checklist"
    ]

    if len(saves) != 1:
        raise ValueError(
            "Cannot identify the checklist save call."
        )

    references = next(
        (
            keyword.value
            for keyword in saves[0].keywords
            if keyword.arg == "_review_new_references"
        ),
        None,
    )

    if not isinstance(references, ast.Dict):
        raise ValueError(
            "Missing transactional new-reference mapping."
        )

    expected = {
        field: "cru_new_" + field
        for field in fields
    }

    actual = {
        key.value: value.id
        for key, value in zip(
            references.keys,
            references.values,
        )
        if isinstance(key, ast.Constant)
        and isinstance(value, ast.Name)
    }

    if actual != expected:
        raise ValueError(
            "Unexpected transactional new-reference mapping."
        )

    clear.body = ast.parse(
        "_crf_from_template(owner_id, entry_id, values)"
    ).body

    # Remove the obsolete text-input helper itself.
    edits = [
        (
            definition_start(old_input),
            old_input.end_lineno,
            "",
        )
    ]

    for function in (editor, clear):
        ast.fix_missing_locations(function)

        edits.append(
            (
                definition_start(function),
                function.end_lineno,
                ast.unparse(function) + "\n\n",
            )
        )

    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(
            edits,
            edits[1:],
        )
    ):
        raise ValueError(
            "Overlapping source edits."
        )

    lines = source.splitlines(
        keepends=True
    )

    for start, end, text in reversed(edits):
        lines[start:end] = [text]

    intermediate = "".join(lines)

    first = next(
        node
        for node in ast.parse(intermediate).body
        if isinstance(
            node,
            (ast.FunctionDef, ast.ClassDef),
        )
    )

    lines = intermediate.splitlines(
        keepends=True
    )

    lines.insert(
        definition_start(first),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<checklist-review-single-input>",
        "exec",
    )

    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_cru_input"
        for node in ast.walk(ast.parse(updated))
    ):
        raise ValueError(
            "An extra-input call remains. "
            "Application was not changed."
        )

    permitted = helpers | {
        "render_checklist_editor",
        "_cru_clear_for_template",
        "_cru_input",
    }

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside "
            "reference-widget integration points."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Use one suggestion selector per Checklist Review "
            "reference field, with typed new names."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    app = Path(
        parser.parse_args().app_file
    ).resolve()

    if not app.is_file():
        raise SystemExit(
            f"Application file not found: {app}"
        )

    original = app.read_bytes()

    try:
        updated, changed = patch_application(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}\n"
            "Apply implement-update-feature-for-checklist-review.py "
            "before this correction."
        ) from error

    if not changed:
        print(
            "Single-input Checklist Review reference selectors "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-single-review-inputs-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed during validation. "
                "Retry the patch."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app.parent,
            prefix=f".{app.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated)

        shutil.copymode(
            app,
            temporary,
        )

        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed before replacement. "
                "Retry the patch."
            )

        temporary.replace(app)
        temporary = None

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            temporary.unlink()

    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print("Syntax and change-scope validation passed.")
    print(
        "Removed the extra New name inputs "
        "from Checklist Review."
    )
    print(
        "Type directly in each selector, press Enter, "
        "then click Update Checklist."
    )
    print(
        "New records are registered only when "
        "the checklist update succeeds."
    )
    print(
        "Existing transaction, filter-restoration, "
        "and weight-protection logic was preserved."
    )
    print(
        "Restart Streamlit. Native selectbox "
        "accept_new_options support is required."
    )
    print(
        "Interactive browser testing remains required."
    )


if __name__ == "__main__":
    main()
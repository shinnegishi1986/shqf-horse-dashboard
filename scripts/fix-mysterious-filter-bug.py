# scripts/fix-filter-glitch.py
#
# Protects Checklist Review filters when a checklist is updated.
#
# Changes:
#   - Captures the current filter/widget state before an update.
#   - Restores it before filter widgets are created on the next rerun.
#   - Preserves the stored horse weight if the editor supplies an empty/zero
#     weight, unless "Clear stored horse weight" is explicitly checked.
#
# Preserves:
#   - First-filter and second-filter settings.
#   - Optional-filter checkboxes.
#   - Existing chart and weight-distribution conditions.
#   - Filter history.
#
# Records that genuinely no longer match the active filters will still
# disappear from the results after an update.
#
# This patch addresses filter-state loss and accidental weight clearing.
# It does not invent missing weights or change existing missing-weight records.
#
# Run:
#   python scripts/fix-filter-glitch.py
#
# Or specify the application file:
#   python scripts/fix-filter-glitch.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# REVIEW_UPDATE_FILTER_AND_WEIGHT_PROTECTION_V1"


HELPERS = r'''
# REVIEW_UPDATE_FILTER_AND_WEIGHT_PROTECTION_V1
def _review_filter_restore_key(owner_id):
    return f"review_pending_filter_restore_{owner_id}"


def _capture_review_update_filter_state(owner_id):
    from copy import deepcopy

    prefixes = (
        f"saved_filter_{owner_id}_",
        f"second_filter_{owner_id}_",
    )

    return {
        key: deepcopy(value)
        for key, value in st.session_state.items()
        if isinstance(key, str) and key.startswith(prefixes)
    }


def _queue_review_update_filter_restore(owner_id, snapshot):
    from copy import deepcopy

    st.session_state[_review_filter_restore_key(owner_id)] = deepcopy(
        snapshot
    )


def _restore_review_update_filter_state(owner_id):
    snapshot = st.session_state.pop(
        _review_filter_restore_key(owner_id),
        None,
    )

    if not isinstance(snapshot, dict):
        return

    prefixes = (
        f"saved_filter_{owner_id}_",
        f"second_filter_{owner_id}_",
    )

    # This runs before Checklist Review creates its widgets.
    for key, value in snapshot.items():
        if isinstance(key, str) and key.startswith(prefixes):
            st.session_state[key] = value


def _review_editor_weight_value(
    entered_weight,
    existing_weight,
    clear_weight,
):
    if clear_weight:
        return None

    parsed_weight = to_optional_float(entered_weight)

    if parsed_weight is not None:
        return parsed_weight

    # Preserve the stored value rather than turning an empty editor value
    # into a destructive update.
    return existing_weight

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


def assignment_to(node, name):
    return (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == name
            for target in node.targets
        )
    )


def named_call(node, name):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def streamlit_rerun(statement):
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "st"
        and statement.value.func.attr == "rerun"
    )


class PatchChecklistEditor(ast.NodeTransformer):
    def __init__(self):
        self.weight_input_count = 0
        self.update_call_count = 0
        self.success_rerun_count = 0

    def visit_Assign(self, node):
        node = self.generic_visit(node)

        if assignment_to(node, "edit_horse_weight"):
            value = node.value

            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name)
                and value.func.value.value if False else False
            ):
                # Validate explicitly below without changing the call.
                pass

            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "st"
                and value.func.attr == "number_input"
            ):
                raise ValueError(
                    "Unexpected horse-weight editor input."
                )

            self.weight_input_count += 1

            checkbox = ast.parse(
                '''
clear_stored_horse_weight = st.checkbox(
    "Clear stored horse weight",
    value=False,
    key=f"review_clear_horse_weight_{owner_id}_{entry['id']}",
    help=(
        "Leave unchecked to preserve the stored weight when "
        "the weight input is empty or zero."
    ),
)
'''
            ).body[0]

            return [node, checkbox]

        if named_call(node.value, "update_checklist"):
            self.update_call_count += 1
            call = node.value

            weight_keywords = [
                keyword
                for keyword in call.keywords
                if keyword.arg == "horse_weight"
            ]

            if len(weight_keywords) != 1:
                raise ValueError(
                    "Could not identify the update's horse_weight argument."
                )

            weight_keywords[0].value = ast.parse(
                """
_review_editor_weight_value(
    edit_horse_weight,
    entry.get("horse_weight"),
    clear_stored_horse_weight,
)
""",
                mode="eval",
            ).body

            snapshot = ast.parse(
                """
_review_update_filter_snapshot = (
    _capture_review_update_filter_state(owner_id)
)
"""
            ).body[0]

            return [snapshot, node]

        return node

    def visit_If(self, node):
        # Only modify reruns in the update-submit branch.
        if (
            isinstance(node.test, ast.Name)
            and node.test.id == "update_clicked"
        ):
            node = self.generic_visit(node)

            success_blocks = [
                statement
                for statement in node.body
                if (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.Name)
                    and statement.test.id == "success"
                )
            ]

            if len(success_blocks) != 1:
                raise ValueError(
                    "Could not uniquely identify the update-success branch."
                )

            success_block = success_blocks[0]
            new_body = []

            for statement in success_block.body:
                if streamlit_rerun(statement):
                    new_body.extend(
                        ast.parse(
                            """
_queue_review_update_filter_restore(
    owner_id,
    _review_update_filter_snapshot,
)
"""
                        ).body
                    )
                    self.success_rerun_count += 1

                new_body.append(statement)

            success_block.body = new_body
            return node

        return self.generic_visit(node)


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    editor = find_function(tree, "render_checklist_editor")
    review = find_function(tree, "render_checklist_review_page")
    find_function(tree, "to_optional_float")

    if editor.decorator_list or review.decorator_list:
        raise ValueError(
            "Unexpected decorators on Checklist Review functions."
        )

    editor_span = (editor.lineno - 1, editor.end_lineno)
    review_span = (review.lineno - 1, review.end_lineno)

    transformer = PatchChecklistEditor()
    updated_editor = transformer.visit(editor)

    if transformer.weight_input_count != 1:
        raise ValueError(
            "Could not uniquely identify the horse-weight editor input."
        )

    if transformer.update_call_count != 1:
        raise ValueError(
            "Could not uniquely identify the checklist update call."
        )

    if transformer.success_rerun_count != 1:
        raise ValueError(
            "Could not uniquely identify the successful update rerun."
        )

    owner_assignments = [
        index
        for index, statement in enumerate(review.body)
        if assignment_to(statement, "owner_id")
    ]

    if len(owner_assignments) != 1:
        raise ValueError(
            "Could not uniquely identify the review owner assignment."
        )

    insertion = owner_assignments[0] + 1

    review.body[insertion:insertion] = ast.parse(
        "_restore_review_update_filter_state(owner_id)"
    ).body

    ast.fix_missing_locations(updated_editor)
    ast.fix_missing_locations(review)

    edits = [
        (
            editor_span[0],
            editor_span[1],
            HELPERS.strip("\n")
            + "\n\n"
            + ast.unparse(updated_editor)
            + "\n\n",
        ),
        (
            review_span[0],
            review_span[1],
            ast.unparse(review) + "\n\n",
        ),
    ]

    lines = source.splitlines(keepends=True)

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<review-filter-glitch-fix>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    changed_functions = {
        "render_checklist_editor",
        "render_checklist_review_page",
        "_review_filter_restore_key",
        "_capture_review_update_filter_state",
        "_queue_review_update_filter_restore",
        "_restore_review_update_filter_state",
        "_review_editor_weight_value",
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
            "Unexpected changes outside the review/editor protection."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid filter-glitch patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Preserve review filters and prevent accidental horse-weight "
            "clearing when updating a checklist."
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
        print(f"The filter-glitch patch is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-filter-glitch-fix.bak"
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
    print("Review filters are restored after successful checklist updates.")
    print("Stored horse weights are preserved unless explicitly cleared.")
    print("Existing records with missing weights are not modified.")
    print("Restart or redeploy the application to apply the patch.")
    print("Interactive update and filter testing are still required.")


if __name__ == "__main__":
    main()
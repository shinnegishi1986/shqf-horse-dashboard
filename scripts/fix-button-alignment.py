# scripts/fix-button-alignment.py
#
# Fixes the vertical offset between:
#   Clear All Filters | Last Filter | Next Filter | Clear History
#
# Removes duplicate Filter History headings that add extra vertical space
# inside the right-hand side of the existing Filter Actions group.
#
# Keeps:
#   - The Filter Actions group.
#   - Matching Current Filters / Filter History section labels.
#   - Existing button keys, callbacks, and disabled states.
#   - Filter history, filtering, and database records.
#
# Requires the previous scripts/fix-buttons.py patch.
#
# Run:
#   python scripts/fix-button-alignment.py
#
# Or:
#   python scripts/fix-button-alignment.py app.py
#
# Creates a backup before changing the application.

import argparse
import ast
import re
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_FILTER_BUTTON_ALIGNMENT_V1"
CONTROL_HELPER = "_review_filter_control_in_column"


def normalized_heading(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def heading_call_details(call):
    if not isinstance(call, ast.Call):
        return None

    # A heading routed through the previous column-placement helper:
    # helper(column, st.subheader, "Filter History")
    if (
        isinstance(call.func, ast.Name)
        and call.func.id == CONTROL_HELPER
        and len(call.args) >= 3
    ):
        function = call.args[1]
        arguments = call.args[2:]
    else:
        function = call.func
        arguments = call.args

    if not (
        isinstance(function, ast.Attribute)
        and function.attr in {
            "header",
            "subheader",
            "markdown",
            "write",
            "text",
            "caption",
        }
    ):
        return None

    text = arguments[0] if arguments else next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg in {"body", "label"}
        ),
        None,
    )

    if not (
        isinstance(text, ast.Constant)
        and isinstance(text.value, str)
    ):
        return None

    return function.attr, text.value


class RemoveDuplicateHistoryHeadings(ast.NodeTransformer):
    def __init__(self):
        self.removed = 0

    def visit_FunctionDef(self, node):
        # Do not alter nested callback definitions.
        return node

    def visit_AsyncFunctionDef(self, node):
        return node

    def visit_Expr(self, node):
        details = heading_call_details(node.value)

        if details is None:
            return self.generic_visit(node)

        method, text = details

        if normalized_heading(text) != "filter history":
            return self.generic_visit(node)

        # Preserve the section label created by scripts/fix-buttons.py.
        if method == "markdown" and text.strip() == "##### Filter History":
            return node

        self.removed += 1

        # A pass statement preserves valid syntax even if the removed
        # heading was the only statement in an existing with/if block.
        return ast.copy_location(ast.Pass(), node)


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


def is_history_renderer(function):
    name = function.name.lower()

    return (
        "history" in name
        and (
            name.startswith("render_")
            or name.startswith("_render_")
            or name.startswith("show_")
            or name.startswith("_show_")
        )
    )


def validate_scope(original, updated, changed_names):
    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in changed_names
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the review/history renderers."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid alignment patch marker.")


def patch_application(source):
    if MARKER in source:
        return source, []

    if "# REVIEW_FILTER_ACTIONS_LABELED_GROUP_V1" not in source:
        raise ValueError(
            "The labeled Filter Actions group is not installed. "
            "Apply scripts/fix-buttons.py first."
        )

    tree = ast.parse(source)
    review = find_function(tree, "render_checklist_review_page")

    candidates = [review]

    candidates.extend(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node is not review
        and is_history_renderer(node)
    )

    edits = []
    changed_names = []

    for function in candidates:
        start_line = min(
            [function.lineno]
            + [
                decorator.lineno
                for decorator in function.decorator_list
            ]
        ) - 1

        end_line = function.end_lineno

        transformer = RemoveDuplicateHistoryHeadings()

        function.body = [
            transformer.visit(statement)
            for statement in function.body
        ]

        if not transformer.removed:
            continue

        ast.fix_missing_locations(function)

        edits.append(
            (
                start_line,
                end_line,
                ast.unparse(function) + "\n\n",
            )
        )

        changed_names.append(function.name)

    if not edits:
        raise ValueError(
            "No duplicate Filter History heading was found in the "
            "review/history renderers. Application was not changed. "
            "The current app.py is needed to identify another source "
            "of spacing."
        )

    ordered = sorted(edits, key=lambda item: item[0])

    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Overlapping function replacements detected.")

    lines = source.splitlines(keepends=True)

    for start, end, replacement in reversed(ordered):
        lines[start:end] = [replacement]

    # Place the idempotency marker before the first replaced function.
    lines.insert(ordered[0][0], MARKER + "\n")

    updated = "".join(lines)

    compile(updated, "<review-button-alignment>", "exec")
    validate_scope(source, updated, set(changed_names))

    return updated, changed_names


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Remove duplicate Filter History headings to align the "
            "Checklist Review action buttons."
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

    if MARKER in source:
        print(f"The button-alignment fix is already installed: {app_path}")
        return

    try:
        updated, changed_names = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-button-alignment.bak"
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
    print("Removed duplicate Filter History headings.")
    print("Kept the matching section labels in the Filter Actions group.")
    print("Updated renderers:")
    for name in changed_names:
        print(f"  - {name}")
    print("Button callbacks, widget keys, and records are unchanged.")
    print("Restart or redeploy the app, then reload Checklist Review.")
    print("Check button alignment at your usual browser width.")
    print("Interactive visual testing is still required.")


if __name__ == "__main__":
    main()
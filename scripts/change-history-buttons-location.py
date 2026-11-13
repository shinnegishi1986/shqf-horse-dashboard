# scripts/change-history-buttons-location.py
#
# Places the Checklist Review filter-history controls on the same row
# as the Clear All Filters button.
#
# Layout:
#   Left column:  Clear All Filters
#   Right column: Filter history controls
#
# Existing callbacks, widget keys, and filter-history behavior are preserved.
#
# Run:
#   python scripts/change-history-buttons-location.py
#
# Or:
#   python scripts/change-history-buttons-location.py app.py
#
# Creates a backup before changing the application.

import argparse
import ast
import re
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_FILTER_HISTORY_SHARED_ROW_V1"
HELPER_NAME = "_review_filter_control_in_column"
COLUMNS_NAME = "_review_filter_action_columns"


HELPER = r'''
# REVIEW_FILTER_HISTORY_SHARED_ROW_V1
def _review_filter_control_in_column(column, render_function, *args, **kwargs):
    with column:
        return render_function(*args, **kwargs)

'''


DISPLAY_METHODS = {
    "button",
    "selectbox",
    "radio",
    "pills",
    "segmented_control",
    "expander",
    "popover",
    "markdown",
    "caption",
    "write",
    "text",
    "subheader",
}


def normalize_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return ""


def widget_identifiers(call):
    values = []

    # Inspect the label and key, rather than all arguments. Options can
    # legitimately contain unrelated words such as "history".
    if call.args:
        label = call.args[0]

        if isinstance(label, ast.Constant) and isinstance(label.value, str):
            values.append(normalize_text(label.value))

    for keyword in call.keywords:
        if keyword.arg not in {"key", "label", "body"}:
            continue

        for node in ast.walk(keyword.value):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.append(normalize_text(node.value))

    return values


def classify_control(call):
    name = call_name(call)
    normalized_name = normalize_text(name)

    # Support an existing dedicated history-rendering helper.
    if (
        isinstance(call.func, ast.Name)
        and normalized_name.startswith(("render ", "show "))
        and "filter" in normalized_name
        and "history" in normalized_name
    ):
        return "history"

    if not (
        isinstance(call.func, ast.Attribute)
        and name in DISPLAY_METHODS
    ):
        return None

    identifiers = widget_identifiers(call)

    if name == "button":
        for text in identifiers:
            words = set(text.split())

            if (
                {"clear", "all", "filters"}.issubset(words)
                or {"clear", "all", "filter"}.issubset(words)
            ):
                return "clear"

    for text in identifiers:
        words = set(text.split())

        if "filter" in words and "history" in words:
            return "history"

        if "filters" in words and "history" in words:
            return "history"

        if name == "button":
            if (
                ("filter" in words or "filters" in words)
                and words.intersection({"undo", "redo", "previous", "next"})
            ):
                return "history"

    return None


class MoveControls(ast.NodeTransformer):
    def __init__(self):
        self.clear_count = 0
        self.history_count = 0

    def visit_FunctionDef(self, node):
        # Do not move controls inside a separately defined callback.
        return node

    def visit_AsyncFunctionDef(self, node):
        return node

    def visit_Call(self, node):
        category = classify_control(node)

        if category is None:
            return self.generic_visit(node)

        column_index = 0 if category == "clear" else 1

        if category == "clear":
            self.clear_count += 1
        else:
            self.history_count += 1

        # Do not recursively wrap children of an already moved control.
        # In particular, an existing history-rendering helper is moved
        # as a single unit.
        return ast.copy_location(
            ast.Call(
                func=ast.Name(
                    id=HELPER_NAME,
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Subscript(
                        value=ast.Name(
                            id=COLUMNS_NAME,
                            ctx=ast.Load(),
                        ),
                        slice=ast.Constant(value=column_index),
                        ctx=ast.Load(),
                    ),
                    node.func,
                    *node.args,
                ],
                keywords=node.keywords,
            ),
            node,
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


def contains_moved_control(statement):
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == HELPER_NAME
        for node in ast.walk(statement)
    )


def validate_scope(original, updated):
    permitted_functions = {
        "render_checklist_review_page",
        HELPER_NAME,
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted_functions
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the review layout and helper."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid layout patch marker.")


def patch_application(source):
    if MARKER in source:
        return source, 0

    tree = ast.parse(source)
    review = find_function(tree, "render_checklist_review_page")

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == HELPER_NAME
        for node in tree.body
    ):
        raise ValueError(
            "The layout helper already exists without its patch marker."
        )

    if any(
        isinstance(node, ast.Name)
        and node.id == COLUMNS_NAME
        for node in ast.walk(review)
    ):
        raise ValueError("The proposed layout variable already exists.")

    start_line = min(
        [review.lineno]
        + [
            decorator.lineno
            for decorator in review.decorator_list
        ]
    ) - 1

    end_line = review.end_lineno

    mover = MoveControls()

    # Transform the page body, not the function definition itself.
    review.body = [
        mover.visit(statement)
        for statement in review.body
    ]

    if mover.clear_count != 1:
        raise ValueError(
            "Could not uniquely identify the Clear All Filters button. "
            f"Found {mover.clear_count}. Application was not changed."
        )

    if mover.history_count == 0:
        raise ValueError(
            "Could not identify the filter-history controls in the review "
            "page. Application was not changed. The current app.py is "
            "needed to match their exact labels or rendering helper."
        )

    insertion_position = next(
        index
        for index, statement in enumerate(review.body)
        if contains_moved_control(statement)
    )

    # Create one shared row before either group of controls is rendered.
    review.body.insert(
        insertion_position,
        ast.parse(
            f"{COLUMNS_NAME} = st.columns([1, 3])"
        ).body[0],
    )

    ast.fix_missing_locations(review)

    replacement = (
        HELPER.strip("\n")
        + "\n\n"
        + ast.unparse(review)
        + "\n\n"
    )

    lines = source.splitlines(keepends=True)
    lines[start_line:end_line] = [replacement]

    updated = "".join(lines)

    compile(updated, "<review-filter-history-layout>", "exec")
    validate_scope(source, updated)

    return updated, mover.history_count


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Place Checklist Review filter-history controls on the "
            "same row as Clear All Filters."
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
        print(f"The filter-history layout is already installed: {app_path}")
        return

    try:
        updated, history_count = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-history-buttons-location.bak"
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
    print("Clear All Filters is placed in the left column.")
    print(
        f"Moved {history_count} filter-history control(s) "
        "to the right column of the same row."
    )
    print("Existing widget keys, callbacks, and filtering are preserved.")
    print("Restart or redeploy the application to view the layout.")
    print("Desktop and mobile visual testing are still required.")


if __name__ == "__main__":
    main()
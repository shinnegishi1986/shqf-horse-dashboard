# scripts/fix-buttons.py
#
# Groups the Checklist Review filter actions inside one labeled block:
#
#   Filter Actions
#   ┌──────────────────────┬──────────────────────────┐
#   │ Current Filters      │ Filter History           │
#   │ Clear All Filters    │ History / Clear History  │
#   └──────────────────────┴──────────────────────────┘
#
# Preserves existing widget labels, keys, callbacks, and behavior.
#
# Requires the previous:
#   scripts/change-history-buttons-location.py
#
# Run:
#   python scripts/fix-buttons.py
#
# Or:
#   python scripts/fix-buttons.py app.py
#
# Creates a backup before changing the application.

import argparse
import ast
import re
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_FILTER_ACTIONS_LABELED_GROUP_V1"
COLUMN_VARIABLE = "_review_filter_action_columns"
CONTROL_HELPER = "_review_filter_control_in_column"


def normalized(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


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


def is_clear_history_button(node):
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "button"
    ):
        return False

    expressions = list(node.args[:1])

    expressions.extend(
        keyword.value
        for keyword in node.keywords
        if keyword.arg in {"label", "key"}
    )

    for expression in expressions:
        for item in ast.walk(expression):
            if (
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
            ):
                words = set(normalized(item.value).split())

                if "history" in words and words.intersection(
                    {"clear", "delete", "reset"}
                ):
                    return True

    return False


class IncludeClearHistory(ast.NodeTransformer):
    def __init__(self):
        self.added = 0

    def visit_FunctionDef(self, node):
        return node

    def visit_AsyncFunctionDef(self, node):
        return node

    def visit_Call(self, node):
        # Already-positioned controls must not be wrapped twice.
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == CONTROL_HELPER
        ):
            return node

        if is_clear_history_button(node):
            self.added += 1

            return ast.copy_location(
                ast.Call(
                    func=ast.Name(
                        id=CONTROL_HELPER,
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Subscript(
                            value=ast.Name(
                                id=COLUMN_VARIABLE,
                                ctx=ast.Load(),
                            ),
                            slice=ast.Constant(value=1),
                            ctx=ast.Load(),
                        ),
                        node.func,
                        *node.args,
                    ],
                    keywords=node.keywords,
                ),
                node,
            )

        return self.generic_visit(node)


def is_columns_assignment(node):
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == COLUMN_VARIABLE
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "st"
        and node.value.func.attr == "columns"
    )


class GroupActionColumns(ast.NodeTransformer):
    def __init__(self):
        self.changed = 0

    def visit_FunctionDef(self, node):
        return node

    def visit_AsyncFunctionDef(self, node):
        return node

    def visit_Assign(self, node):
        if not is_columns_assignment(node):
            return self.generic_visit(node)

        self.changed += 1

        group = ast.parse(
            f'''
with st.container(border=True):
    st.markdown("#### Filter Actions")
    {COLUMN_VARIABLE} = st.columns([1, 3])
    with {COLUMN_VARIABLE}[0]:
        st.markdown("##### Current Filters")
    with {COLUMN_VARIABLE}[1]:
        st.markdown("##### Filter History")
'''
        ).body[0]

        # Preserve the previously configured column proportions.
        group.body[1] = node

        return ast.copy_location(group, node)


def validate_scope(original, updated):
    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == "render_checklist_review_page"
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside render_checklist_review_page."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid filter-actions patch marker.")


def patch_application(source):
    if MARKER in source:
        return source, 0

    tree = ast.parse(source)

    review = find_function(tree, "render_checklist_review_page")

    try:
        find_function(tree, CONTROL_HELPER)
    except ValueError as error:
        raise ValueError(
            "The previous history-buttons layout patch is required. "
            "Apply scripts/change-history-buttons-location.py first."
        ) from error

    start_line = min(
        [review.lineno]
        + [
            decorator.lineno
            for decorator in review.decorator_list
        ]
    ) - 1

    end_line = review.end_lineno

    clear_history = IncludeClearHistory()

    review.body = [
        clear_history.visit(statement)
        for statement in review.body
    ]

    grouper = GroupActionColumns()

    review.body = [
        grouper.visit(statement)
        for statement in review.body
    ]

    if grouper.changed != 1:
        raise ValueError(
            "Could not uniquely identify the shared filter-action row. "
            f"Found {grouper.changed}. Application was not changed."
        )

    # Verify that the existing routed controls are still present.
    routed_controls = [
        node
        for node in ast.walk(review)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == CONTROL_HELPER
        )
    ]

    if len(routed_controls) < 2:
        raise ValueError(
            "Expected both filter and history controls in the shared row."
        )

    ast.fix_missing_locations(review)

    replacement = (
        MARKER
        + "\n"
        + ast.unparse(review)
        + "\n\n"
    )

    lines = source.splitlines(keepends=True)
    lines[start_line:end_line] = [replacement]

    updated = "".join(lines)

    compile(updated, "<review-filter-actions-group>", "exec")
    validate_scope(source, updated)

    return updated, clear_history.added


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Group Clear All Filters and filter-history actions "
            "inside one labeled Checklist Review block."
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
        print(f"The labeled filter-actions group is installed: {app_path}")
        return

    try:
        updated, added_history_buttons = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-filter-actions-group.bak"
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
    print("Created one bordered Filter Actions group.")
    print("Left section: Current Filters.")
    print("Right section: Filter History.")
    print(
        "Additional Clear History buttons moved into the group: "
        f"{added_history_buttons}"
    )
    print("Existing widget keys, callbacks, and behavior are preserved.")
    print("Database records and filter values were not changed.")
    print("Restart or redeploy the application to view the changes.")
    print("Interactive layout testing is still required.")


if __name__ == "__main__":
    main()
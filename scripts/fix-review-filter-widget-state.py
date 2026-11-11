# scripts/fix-review-filter-widget-state.py
#
# Fix:
#   StreamlitValueAssignmentNotAllowedError when updating a horse
#   because filter snapshots include file-uploader/button widget state.
#
# Run:
#   python scripts/fix-review-filter-widget-state.py
#
# Or:
#   python scripts/fix-review-filter-widget-state.py app.py
#
# Changes:
#   - Excludes protected widget keys from review filter snapshots.
#   - Prevents restoring protected widget keys from existing snapshots.
#   - Preserves normal editable filter values.
#
# Does NOT:
#   - Change horse/checklist database records.
#   - Reset ordinary filter values.
#   - Remove upload/download buttons.
#   - Change the review table or charts.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_PROTECTED_WIDGET_STATE_FIX_V1"

PROTECTED_WIDGETS = {
    "file_uploader",
    "button",
    "download_button",
    "form_submit_button",
    "camera_input",
    "audio_input",
    "data_editor",
    "form",
}

HELPER_TEMPLATE = '''
# REVIEW_PROTECTED_WIDGET_STATE_FIX_V1
def _review_is_protected_filter_widget(key, owner_id):
    if not isinstance(key, str):
        return False

    # Explicitly covers the uploader identified in the reported error.
    protected_keys = {
        f"saved_filter_{owner_id}_backup_import_file",
        f"second_filter_{owner_id}_backup_import_file",
    }

    protected_keys.update([
        __DISCOVERED_KEYS__
    ])

    return key in protected_keys

'''


def is_session_state(node):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "st"
        and node.attr == "session_state"
    )


def is_session_subscript(node):
    return (
        isinstance(node, ast.Subscript)
        and is_session_state(node.value)
    )


def function_arguments(function):
    arguments = function.args
    return {
        item.arg
        for item in (
            arguments.posonlyargs
            + arguments.args
            + arguments.kwonlyargs
        )
    }


def discover_protected_key_expressions(tree):
    expressions = {}

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in PROTECTED_WIDGETS
        ):
            continue

        for keyword in node.keywords:
            if keyword.arg != "key":
                continue

            expression = keyword.value

            # Only evaluate key expressions that can safely be reconstructed
            # inside a helper receiving owner_id.
            names = {
                item.id
                for item in ast.walk(expression)
                if isinstance(item, ast.Name)
            }

            if not names.issubset({
                "owner_id",
                "saved_filter_key",
                "second_filter_key",
            }):
                continue

            calls = [
                item
                for item in ast.walk(expression)
                if isinstance(item, ast.Call)
            ]

            if any(
                not (
                    isinstance(call.func, ast.Name)
                    and call.func.id in {
                        "saved_filter_key",
                        "second_filter_key",
                    }
                )
                for call in calls
            ):
                continue

            # Accept simple literals, f-strings, and the app's key helpers.
            if not isinstance(
                expression,
                (ast.Constant, ast.JoinedStr, ast.Call),
            ):
                continue

            text = ast.unparse(expression)
            expressions[text] = expression

    return sorted(expressions)


class ProtectFilterState(ast.NodeTransformer):
    def __init__(self):
        self.guarded_assignments = 0
        self.guarded_comprehensions = 0

    def condition(self, key):
        return ast.UnaryOp(
            op=ast.Not(),
            operand=ast.Call(
                func=ast.Name(
                    id="_review_is_protected_filter_widget",
                    ctx=ast.Load(),
                ),
                args=[
                    key,
                    ast.Name(id="owner_id", ctx=ast.Load()),
                ],
                keywords=[],
            ),
        )

    def visit_Assign(self, node):
        self.generic_visit(node)

        state_targets = [
            target
            for target in node.targets
            if is_session_subscript(target)
        ]

        if not state_targets:
            return node

        if len(node.targets) != 1:
            raise ValueError(
                "Unexpected chained Session State assignment."
            )

        self.guarded_assignments += 1

        return ast.copy_location(
            ast.If(
                test=self.condition(state_targets[0].slice),
                body=[node],
                orelse=[],
            ),
            node,
        )

    def visit_DictComp(self, node):
        self.generic_visit(node)

        # A filter snapshot commonly uses:
        # {key: deepcopy(st.session_state[key]) for key in ...}
        if (
            isinstance(node.key, ast.Name)
            and any(
                is_session_subscript(item)
                for item in ast.walk(node.value)
            )
        ):
            for generator in node.generators:
                if (
                    isinstance(generator.target, ast.Name)
                    and generator.target.id == node.key.id
                ):
                    generator.ifs.insert(
                        0,
                        self.condition(
                            ast.Name(
                                id=node.key.id,
                                ctx=ast.Load(),
                            )
                        ),
                    )

                    self.guarded_comprehensions += 1
                    break

        return node


def patch_application(source):
    if MARKER in source:
        return source, []

    tree = ast.parse(source)
    discovered_keys = discover_protected_key_expressions(tree)

    helper_source = HELPER_TEMPLATE.replace(
        "__DISCOVERED_KEYS__",
        ",\n        ".join(discovered_keys),
    )

    candidates = []

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        name = node.name.lower()

        if (
            "review" in name
            and "filter" in name
            and any(
                word in name
                for word in ("snapshot", "restore", "capture")
            )
            and "owner_id" in function_arguments(node)
        ):
            candidates.append(node)

    if not candidates:
        raise ValueError(
            "Could not find the earlier review filter snapshot/restoration "
            "helpers. Provide the current app.py so their exact structure "
            "can be patched safely."
        )

    lines = source.splitlines(keepends=True)
    edits = []
    changed_names = []
    guarded_restore_count = 0

    for function in candidates:
        if function.decorator_list:
            raise ValueError(
                f"Unexpected decorators on {function.name}."
            )

        start = function.lineno - 1
        end = function.end_lineno

        transformer = ProtectFilterState()
        transformer.visit(function)

        count = (
            transformer.guarded_assignments
            + transformer.guarded_comprehensions
        )

        if not count:
            continue

        guarded_restore_count += transformer.guarded_assignments

        ast.fix_missing_locations(function)

        edits.append(
            (
                start,
                end,
                ast.unparse(function) + "\n\n",
            )
        )

        changed_names.append(function.name)

    if not guarded_restore_count:
        raise ValueError(
            "No direct Session State restoration assignments were found. "
            "The application was not changed."
        )

    insertion_line = min(start for start, _, _ in edits)

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    lines.insert(
        insertion_line,
        helper_source.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(updated, "<protected-review-widget-state>", "exec")

    validate_scope(
        source,
        updated,
        set(changed_names)
        | {"_review_is_protected_filter_widget"},
    )

    return updated, changed_names


def validate_scope(original, updated, permitted_functions):
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
            "Unexpected changes outside the filter-state helpers."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid patch marker.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Prevent review filter restoration from assigning "
            "protected uploader/button widget state."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if MARKER in source:
        print(f"This fix is already installed: {app_path}")
        return

    try:
        updated, changed_names = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup = app_path.with_name(
        f"{app_path.name}.before-protected-widget-state-fix.bak"
    )

    if backup.exists():
        raise SystemExit(
            f"Backup already exists: {backup}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(app_path, backup)
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
            temporary_file.write(updated)
            temporary_path = Path(temporary_file.name)

        shutil.copymode(app_path, temporary_path)
        temporary_path.replace(app_path)

    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    print(f"Updated: {app_path}")
    print(f"Backup: {backup}")
    print("Patched helpers:")
    for name in changed_names:
        print(f"  - {name}")

    print("Python syntax and patch-scope validation passed.")
    print("Protected uploader/button keys will not be restored.")
    print("Ordinary filter values and database records are unchanged.")
    print("Restart the app and reload the browser page before testing.")
    print("Then update one horse record and verify the review page reloads.")
    print("Interactive Streamlit testing has not been performed by this script.")


if __name__ == "__main__":
    main()
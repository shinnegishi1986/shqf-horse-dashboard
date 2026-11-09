# scripts/clear-filter-history-button.py
#
# Adds a "Clear History" button beside Last Filter and Next Filter.
#
# The button uses Streamlit's primary color, while Last Filter and
# Next Filter remain secondary buttons.
#
# Clearing history:
#   - Keeps the currently applied filters unchanged.
#   - Removes previous and forward history.
#   - Keeps the current configuration as the new starting point.
#   - Does not delete saved filters or checklist records.
#
# Run:
#   python scripts/clear-filter-history-button.py
#
# Or specify the application file:
#   python scripts/clear-filter-history-button.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# CLEAR_FILTER_HISTORY_BUTTON_V1"


REPLACEMENT = r'''
# CLEAR_FILTER_HISTORY_BUTTON_V1
def _clear_review_filter_history(owner_id):
    from copy import deepcopy

    current = _capture_review_filter_configuration(owner_id)

    st.session_state[_filter_history_session_key(owner_id)] = {
        "entries": [deepcopy(current)],
        "position": 0,
    }


def render_review_filter_history(owner_id):
    _record_review_filter_history(owner_id)

    history = st.session_state[_filter_history_session_key(owner_id)]
    entries = history["entries"]
    position = history["position"]

    st.markdown("### Filter History")

    previous_column, next_column, clear_column = st.columns(3)

    with previous_column:
        st.button(
            "Last Filter",
            key=f"review_filter_history_previous_{owner_id}",
            type="secondary",
            disabled=position <= 0,
            on_click=_navigate_review_filter_history,
            args=(owner_id, -1),
            use_container_width=True,
        )

    with next_column:
        st.button(
            "Next Filter",
            key=f"review_filter_history_next_{owner_id}",
            type="secondary",
            disabled=position >= len(entries) - 1,
            on_click=_navigate_review_filter_history,
            args=(owner_id, 1),
            use_container_width=True,
        )

    with clear_column:
        st.button(
            "Clear History",
            key=f"review_filter_history_clear_{owner_id}",
            type="primary",
            disabled=len(entries) <= 1,
            on_click=_clear_review_filter_history,
            args=(owner_id,),
            help=(
                "Remove previous and forward history while keeping "
                "the currently applied filters."
            ),
            use_container_width=True,
        )

    st.caption(
        f"Configuration {position + 1} of {len(entries)}"
    )
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


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    for name in (
        "_capture_review_filter_configuration",
        "_filter_history_session_key",
        "_record_review_filter_history",
        "_navigate_review_filter_history",
    ):
        find_function(tree, name)

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_clear_review_filter_history"
        for node in tree.body
    ):
        raise ValueError(
            "A clear-history callback already exists without the expected "
            "patch marker. No changes were applied."
        )

    renderer = find_function(
        tree,
        "render_review_filter_history",
    )

    if renderer.decorator_list:
        raise ValueError(
            "Unexpected decorators on render_review_filter_history."
        )

    lines = source.splitlines(keepends=True)

    updated = (
        "".join(lines[:renderer.lineno - 1])
        + REPLACEMENT.strip("\n")
        + "\n\n"
        + "".join(lines[renderer.end_lineno:])
    )

    compile(updated, "<clear-filter-history-button>", "exec")
    validate_patch_scope(source, updated)

    return updated


def validate_patch_scope(original, updated):
    ignored_functions = {
        "render_review_filter_history",
        "_clear_review_filter_history",
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
            "Unexpected changes outside the filter-history controls."
        )

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid clear-history patch marker.")

    tree = ast.parse(updated)

    find_function(tree, "_clear_review_filter_history")
    find_function(tree, "render_review_filter_history")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add a differently colored Clear History button "
            "to Checklist Review filter history."
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
        print(f"The Clear History button is already applied to: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-clear-filter-history-button.bak"
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
    print("Added Clear History using the primary button color.")
    print("Last Filter and Next Filter remain secondary buttons.")
    print("Clearing history keeps the current filters unchanged.")
    print("Saved filters and checklist records are not deleted.")
    print("Restart or redeploy the application to view the button.")
    print("Interactive Streamlit testing is still required.")


if __name__ == "__main__":
    main()
# scripts/add-filter-history-feature.py
#
# Adds "Last Filter" and "Next Filter" navigation to Checklist Review.
#
# Run:
#   python scripts/add-filter-history-feature.py
#
# Or specify the application file:
#   python scripts/add-filter-history-feature.py app.py
#
# Behavior:
#   - Automatically remembers changes to review filters.
#   - Last Filter restores the previous filter configuration.
#   - Next Filter restores the next configuration after going backward.
#   - Restores both first-filter and second-filter settings.
#   - Preserves forward history until you change a restored configuration.
#   - Making a new change after going backward creates a new history branch.
#   - Does not create extra entries for pagination or unchanged reruns.
#   - Keeps up to 100 configurations per user in the current session.
#
# History is session-only, not a permanent saved-filter backup.
# No database queries or sample data are added.
#
# Existing chart, tooltip, recency, and optional-filter changes are preserved.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# CHECKLIST_FILTER_HISTORY_V1"


HELPERS = r'''
# CHECKLIST_FILTER_HISTORY_V1
FILTER_HISTORY_LIMIT = 100


def _filter_history_session_key(owner_id):
    return f"checklist_filter_history_{owner_id}"


def _filter_history_fields():
    # Pagination is display state, not a filter condition.
    return [
        name
        for name in get_filter_defaults()
        if name not in {"page_size", "page_number"}
    ]


def _capture_review_filter_configuration(owner_id):
    from copy import deepcopy

    defaults = get_filter_defaults()
    fields = _filter_history_fields()

    first = {
        name: deepcopy(
            st.session_state.get(
                saved_filter_key(owner_id, name),
                defaults[name],
            )
        )
        for name in fields
    }

    second = {
        name: deepcopy(
            st.session_state.get(
                second_filter_key(owner_id, name),
                defaults[name],
            )
        )
        for name in fields
    }

    return {
        "first": first,
        "second": second,
        "second_enabled": bool(
            st.session_state.get(
                second_filter_key(owner_id, "enabled"),
                False,
            )
        ),
        "active_filter_title": st.session_state.get(
            saved_filter_key(owner_id, "active_filter_title"),
            "",
        ),
    }


def _review_filter_configurations_equal(left, right):
    # A saved-filter title is metadata, not a filtering condition.
    return (
        left["first"] == right["first"]
        and left["second"] == right["second"]
        and left["second_enabled"] == right["second_enabled"]
    )


def _record_review_filter_history(owner_id):
    from copy import deepcopy

    key = _filter_history_session_key(owner_id)
    current = _capture_review_filter_configuration(owner_id)
    history = st.session_state.get(key)

    if not isinstance(history, dict) or not history.get("entries"):
        st.session_state[key] = {
            "entries": [deepcopy(current)],
            "position": 0,
        }
        return

    entries = history["entries"]
    position = max(
        0,
        min(int(history.get("position", 0)), len(entries) - 1),
    )

    if _review_filter_configurations_equal(
        entries[position],
        current,
    ):
        # Update metadata without adding a duplicate configuration.
        entries[position]["active_filter_title"] = current[
            "active_filter_title"
        ]
        history["position"] = position
        st.session_state[key] = history
        return

    # A changed configuration after backward navigation starts a new branch.
    entries = entries[:position + 1]
    entries.append(deepcopy(current))

    if len(entries) > FILTER_HISTORY_LIMIT:
        entries = entries[-FILTER_HISTORY_LIMIT:]

    st.session_state[key] = {
        "entries": entries,
        "position": len(entries) - 1,
    }


def _restore_review_filter_configuration(owner_id, configuration):
    from copy import deepcopy

    defaults = get_filter_defaults()

    # This function runs in a button callback, before the next script run
    # instantiates filter widgets.
    reset_filter_values(owner_id)
    reset_second_filter_values(owner_id)

    for name in _filter_history_fields():
        st.session_state[saved_filter_key(owner_id, name)] = deepcopy(
            configuration["first"].get(name, defaults[name])
        )

        st.session_state[second_filter_key(owner_id, name)] = deepcopy(
            configuration["second"].get(name, defaults[name])
        )

    st.session_state[
        saved_filter_key(owner_id, "active_filter_title")
    ] = configuration.get("active_filter_title", "")

    st.session_state[
        second_filter_key(owner_id, "enabled")
    ] = bool(configuration.get("second_enabled", False))

    # Existing selectbox helpers use load versions to refresh their
    # separate widget keys from the restored filter-state values.
    first_version_key = filter_load_version_key(owner_id)
    second_version_key = second_filter_load_version_key(owner_id)

    st.session_state[first_version_key] = (
        int(st.session_state.get(first_version_key, 0)) + 1
    )

    st.session_state[second_version_key] = (
        int(st.session_state.get(second_version_key, 0)) + 1
    )

    # Restart pagination because the restored result set may be smaller.
    for key_function in (saved_filter_key, second_filter_key):
        st.session_state[key_function(owner_id, "page_number")] = 1

    # This is the page-number widget key used by Checklist Review.
    st.session_state[
        saved_filter_key(owner_id, "page_number_input")
    ] = 1

    # Avoid carrying an editor selection into a different result set.
    st.session_state.pop("selected_review_checklist_id", None)


def _navigate_review_filter_history(owner_id, direction):
    key = _filter_history_session_key(owner_id)
    history = st.session_state.get(key)

    if not isinstance(history, dict):
        return

    entries = history.get("entries") or []

    if not entries:
        return

    position = int(history.get("position", 0))
    target = position + direction

    if target < 0 or target >= len(entries):
        return

    _restore_review_filter_configuration(
        owner_id,
        entries[target],
    )

    history["position"] = target
    st.session_state[key] = history


def render_review_filter_history(owner_id):
    # Called after both sets of filter widgets have updated their state.
    _record_review_filter_history(owner_id)

    history = st.session_state[_filter_history_session_key(owner_id)]
    entries = history["entries"]
    position = history["position"]

    st.markdown("### Filter History")

    previous_column, next_column, status_column = st.columns([1, 1, 2])

    with previous_column:
        st.button(
            "Last Filter",
            key=f"review_filter_history_previous_{owner_id}",
            disabled=position <= 0,
            on_click=_navigate_review_filter_history,
            args=(owner_id, -1),
            use_container_width=True,
        )

    with next_column:
        st.button(
            "Next Filter",
            key=f"review_filter_history_next_{owner_id}",
            disabled=position >= len(entries) - 1,
            on_click=_navigate_review_filter_history,
            args=(owner_id, 1),
            use_container_width=True,
        )

    with status_column:
        st.caption(
            f"Configuration {position + 1} of {len(entries)}"
        )

    st.caption(
        "Filter changes are remembered automatically in this session. "
        "Last Filter goes back; Next Filter goes forward. "
        "Changing a past configuration replaces its forward history. "
        "Pagination does not create history entries. "
        f"Up to {FILTER_HISTORY_LIMIT} configurations are retained."
    )

'''


RENDER_CALL = '''
    render_review_filter_history(owner_id)

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


def is_review_metrics_assignment(statement):
    if not isinstance(statement, ast.Assign):
        return False

    if not any(
        isinstance(target, ast.Name)
        and target.id == "review_metrics"
        for target in statement.targets
    ):
        return False

    call = statement.value

    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "calculate_review_metrics"
    )


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    required_functions = [
        "get_filter_defaults",
        "saved_filter_key",
        "second_filter_key",
        "reset_filter_values",
        "reset_second_filter_values",
        "filter_load_version_key",
        "second_filter_load_version_key",
    ]

    for name in required_functions:
        find_function(tree, name)

    review = find_function(
        tree,
        "render_checklist_review_page",
    )

    if review.decorator_list:
        raise ValueError(
            "Unexpected decorators on render_checklist_review_page."
        )

    anchors = [
        statement
        for statement in review.body
        if is_review_metrics_assignment(statement)
    ]

    if len(anchors) != 1:
        raise ValueError(
            "Could not uniquely locate the review metrics assignment. "
            "No changes were applied."
        )

    # The supplied application calculates review metrics after both
    # first-filter and second-filter widgets have been processed.
    insertion_line = anchors[0].lineno - 1
    lines = source.splitlines(keepends=True)

    lines.insert(insertion_line, RENDER_CALL)
    lines.insert(review.lineno - 1, HELPERS + "\n")

    updated = "".join(lines)

    validate_patch(source, updated)

    return updated


def validate_patch(original, updated):
    compile(updated, "<filter-history-patch>", "exec")

    tree = ast.parse(updated)

    if updated.count(PATCH_MARKER) != 1:
        raise ValueError("Invalid filter-history patch marker.")

    expected_helpers = {
        "_filter_history_session_key",
        "_filter_history_fields",
        "_capture_review_filter_configuration",
        "_review_filter_configurations_equal",
        "_record_review_filter_history",
        "_restore_review_filter_configuration",
        "_navigate_review_filter_history",
        "render_review_filter_history",
    }

    for name in expected_helpers:
        find_function(tree, name)

    review = find_function(
        tree,
        "render_checklist_review_page",
    )

    calls = [
        statement
        for statement in review.body
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "render_review_filter_history"
        )
    ]

    if len(calls) != 1:
        raise ValueError(
            "Expected exactly one filter-history rendering call."
        )

    def normalize(source):
        parsed = ast.parse(source)
        remaining = []

        for node in parsed.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in expected_helpers
            ):
                continue

            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "FILTER_HISTORY_LIMIT"
                    for target in node.targets
                )
            ):
                continue

            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "render_checklist_review_page"
            ):
                node.body = [
                    statement
                    for statement in node.body
                    if not (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id
                        == "render_review_filter_history"
                    )
                ]

            remaining.append(node)

        parsed.body = remaining

        return ast.dump(parsed, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the filter-history feature."
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add Last Filter and Next Filter history navigation "
            "to Checklist Review."
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

    if PATCH_MARKER in source:
        print("The filter-history feature is already applied.")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-filter-history.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename the backup before applying this patch."
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
    print(f"Original application backup: {backup_path}")
    print("Python syntax and patch-scope validation passed.")
    print("Added Last Filter and Next Filter navigation.")
    print("History includes first-filter and second-filter settings.")
    print("History is stored per user in the current session.")
    print("Existing application features were preserved.")
    print("Reload the application to use filter history.")
    print("Interactive Streamlit testing is still required.")


if __name__ == "__main__":
    main()
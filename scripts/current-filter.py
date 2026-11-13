# scripts/current-filter.py
#
# Adds a "Current Review Filters" panel to Checklist Review.
#
# Shows:
#   - Actual arguments received by filter_checklists().
#   - Filter-function defaults included in those arguments.
#   - Input and output record counts for each filtering pass.
#   - Values restored from Session State when they reach the filter function.
#
# Important:
#   A supplied range is not necessarily active when its enable switch is off.
#   The panel explicitly explains this distinction.
#
# Does NOT:
#   - Change filtering logic.
#   - Reset filter state.
#   - Change checklist records.
#   - Change pagination or saved filters.
#   - Capture checklist-row contents in the diagnostic panel.
#
# Run:
#   python scripts/current-filter.py
#
# Or:
#   python scripts/current-filter.py app.py
#
# A backup is created before the application is changed.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# CURRENT_REVIEW_FILTER_DIAGNOSTICS_V1"


HELPERS = r'''
# CURRENT_REVIEW_FILTER_DIAGNOSTICS_V1
def _current_review_filter_safe_value(value):
    import datetime
    import math

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)

    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)

        if isinstance(value, (set, frozenset)):
            items.sort(key=str)

        return [
            _current_review_filter_safe_value(item)
            for item in items
        ]

    if isinstance(value, dict):
        return {
            str(key): _current_review_filter_safe_value(item)
            for key, item in value.items()
        }

    return str(value)


def _current_review_filter_length(value):
    try:
        return len(value)
    except (TypeError, AttributeError):
        return None


def _current_review_filter_is_record_argument(name, value):
    normalized = name.lower()

    if normalized in {
        "checklists",
        "records",
        "entries",
        "rows",
        "data",
        "filtered_checklists",
        "first_filtered_checklists",
        "second_filtered_checklists",
    }:
        return True

    if "checklists" in normalized:
        return True

    if isinstance(value, (list, tuple)) and value:
        first = value[0]

        if isinstance(first, dict):
            return bool(
                {
                    "horse_id",
                    "horse_name",
                    "horse_weight",
                    "race_date",
                }.intersection(first)
            )

    return False


def _current_review_filter_trace(function):
    import functools
    import inspect

    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        captures = st.session_state.get(
            "_current_review_filter_capture_stack",
            [],
        )

        if not captures:
            return function(*args, **kwargs)

        # Capture only actual function arguments, not an unrelated snapshot
        # of all Session State keys.
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        supplied = {}
        source_counts = {}

        for name, value in bound.arguments.items():
            if _current_review_filter_is_record_argument(name, value):
                source_counts[name] = _current_review_filter_length(value)
                continue

            # User identity is not a filtering control to display here.
            if name in {"owner_id", "user_id"}:
                continue

            supplied[name] = _current_review_filter_safe_value(value)

        result = function(*args, **kwargs)

        captures[-1].append({
            "arguments": supplied,
            "source_counts": source_counts,
            "result_count": _current_review_filter_length(result),
        })

        return result

    return wrapped


def _current_review_filter_render(calls):
    import json

    with st.expander("Current Review Filters", expanded=True):
        st.caption(
            "These are the actual arguments received by the checklist "
            "filtering function during this page render. Restored and "
            "default values are included."
        )

        if not calls:
            st.info(
                "The filtering function has not run during this render. "
                "No current filter results were captured."
            )
            return

        for index, call in enumerate(calls, start=1):
            st.markdown(f"#### Filtering pass {index}")

            counts = call["source_counts"]
            output_count = call["result_count"]

            if counts:
                sources = "; ".join(
                    f"{name}: "
                    + (
                        f"{count:,}"
                        if count is not None
                        else "count unavailable"
                    )
                    for name, count in counts.items()
                )

                output_text = (
                    f"{output_count:,}"
                    if output_count is not None
                    else "count unavailable"
                )

                st.write(
                    f"Input records — {sources}. "
                    f"Output records — {output_text}."
                )

                if len(counts) == 1:
                    input_count = next(iter(counts.values()))

                    if (
                        input_count is not None
                        and output_count is not None
                        and output_count < input_count
                    ):
                        st.warning(
                            "This filtering pass reduced the number of "
                            "records. Its supplied values are shown below."
                        )
                    elif (
                        input_count is not None
                        and output_count == input_count
                    ):
                        st.caption(
                            "This pass did not reduce the record count. "
                            "Conditions may still be enabled."
                        )
            else:
                st.write(
                    "Output records: "
                    + (
                        f"{output_count:,}"
                        if output_count is not None
                        else "count unavailable"
                    )
                )

            arguments = call["arguments"]

            rows = [
                {
                    "Filter argument": name,
                    "Value received": json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                }
                for name, value in arguments.items()
            ]

            if rows:
                st.table(rows)
            else:
                st.info("No separate filter arguments were supplied.")

        st.caption(
            "Read enable/apply switches together with their associated "
            "values. A stored range is not necessarily applied when its "
            "switch is false. Null values, empty lists, and default bounds "
            "are shown rather than guessed to be active or inactive."
        )

        st.caption(
            "These counts describe calls to filter_checklists, not the "
            "number of rows visible on the current pagination page. "
            "The input may already be restricted by database loading or "
            "earlier application logic."
        )


def _current_review_filter_page(function):
    import functools

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        # Reserve space above the existing page without changing its
        # filtering, editing, chart, or pagination code.
        panel = st.container()
        calls = []

        state_key = "_current_review_filter_capture_stack"
        stack = st.session_state.get(state_key)

        if stack is None:
            stack = []
            st.session_state[state_key] = stack

        stack.append(calls)

        try:
            return function(*args, **kwargs)
        finally:
            # Remove this page's capture context even during a rerun.
            if stack and stack[-1] is calls:
                stack.pop()

            with panel:
                _current_review_filter_render(calls)

    return wrapped

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


def definition_start(function):
    return min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1


def validate_patch(original, updated):
    before = ast.parse(original)
    after = ast.parse(updated)

    decorators = {
        "filter_checklists": "_current_review_filter_trace",
        "render_checklist_review_page": "_current_review_filter_page",
    }

    for name, decorator_name in decorators.items():
        function = find_function(after, name)

        if not (
            function.decorator_list
            and isinstance(function.decorator_list[0], ast.Name)
            and function.decorator_list[0].id == decorator_name
        ):
            raise ValueError(
                f"The expected diagnostic decorator is missing from {name}."
            )

        # Remove only the newly added decorator for comparison.
        function.decorator_list.pop(0)

    after.body = [
        node
        for node in after.body
        if not (
            isinstance(node, ast.FunctionDef)
            and node.name.startswith("_current_review_filter_")
        )
    ]

    if ast.dump(before, include_attributes=False) != ast.dump(
        after,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes outside the diagnostic helpers/decorators."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid diagnostic patch marker.")


def patch_application(source):
    if MARKER in source:
        return source

    tree = ast.parse(source)

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name.startswith("_current_review_filter_")
        for node in tree.body
    ):
        raise ValueError(
            "A diagnostic helper name already exists without "
            "the expected patch marker."
        )

    filter_function = find_function(tree, "filter_checklists")
    review_function = find_function(
        tree,
        "render_checklist_review_page",
    )

    # Verify that the review code actually calls the function being traced.
    review_calls_filter = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "filter_checklists"
        for node in ast.walk(review_function)
    )

    if not review_calls_filter:
        raise ValueError(
            "The review page does not directly call filter_checklists. "
            "The current app.py needs a more specific integration."
        )

    insertions = {}

    def insert_at(line, text):
        insertions.setdefault(line, []).append(text)

    filter_start = definition_start(filter_function)
    review_start = definition_start(review_function)

    # Helpers must exist before Python evaluates either decorator.
    first_start = min(filter_start, review_start)

    insert_at(
        first_start,
        HELPERS.strip("\n") + "\n\n",
    )

    insert_at(
        filter_start,
        "@_current_review_filter_trace\n",
    )

    insert_at(
        review_start,
        "@_current_review_filter_page\n",
    )

    lines = source.splitlines(keepends=True)

    for line in sorted(insertions, reverse=True):
        lines.insert(line, "".join(insertions[line]))

    updated = "".join(lines)

    compile(updated, "<current-review-filter-diagnostics>", "exec")
    validate_patch(source, updated)

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Show actual Checklist Review filter arguments "
            "and record counts."
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
        print(f"Current Review Filters is already installed: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-current-filter-panel.bak"
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
    print("Added the Current Review Filters panel above Checklist Review.")
    print("The panel shows actual filtering arguments and record counts.")
    print("No filtering logic, records, or existing filter values changed.")
    print("Restart or redeploy the application, then open Checklist Review.")
    print(
        "Compare input/output counts and the enable/apply switches "
        "when results appear unexpectedly restricted."
    )
    print("Interactive Streamlit testing is still required.")


if __name__ == "__main__":
    main()
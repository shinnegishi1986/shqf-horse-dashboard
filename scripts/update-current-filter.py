# scripts/update-current-filter.py
#
# Fix: fix-current-filder-visibility
#
# Changes:
#   - Collapses "Current Review Filters" by default.
#   - Places the panel immediately below the Checklist Review header.
#   - Preserves filter diagnostics, filtering, and record counts.
#
# Run:
#   python scripts/update-current-filter.py
#
# Or:
#   python scripts/update-current-filter.py app.py
#
# Requires the earlier scripts/current-filter.py patch.
# Creates a backup before changing the application.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# CURRENT_FILTER_VISIBILITY_BELOW_HEADER_V1"


REPLACEMENT_WRAPPER = r'''
# CURRENT_FILTER_VISIBILITY_BELOW_HEADER_V1
def _current_review_filter_place_panel():
    stack = st.session_state.get(
        "_current_review_filter_capture_stack",
        [],
    )

    if stack:
        stack[-1].panel = st.container()


def _current_review_filter_page(function):
    import functools

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        class ReviewFilterCalls(list):
            pass

        calls = ReviewFilterCalls()
        calls.panel = None

        state_key = "_current_review_filter_capture_stack"
        stack = st.session_state.get(state_key)

        if stack is None:
            stack = []
            st.session_state[state_key] = stack

        stack.append(calls)

        try:
            return function(*args, **kwargs)
        finally:
            if stack and stack[-1] is calls:
                stack.pop()

            # The original review function reserves this container directly
            # after its header. Do not create a fallback above the header.
            if calls.panel is not None:
                with calls.panel:
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


def is_review_header(statement):
    if not (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
    ):
        return False

    call = statement.value

    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr in {"header", "title", "subheader"}
    ):
        return False

    heading = call.args[0] if call.args else next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "body"
        ),
        None,
    )

    return (
        isinstance(heading, ast.Constant)
        and isinstance(heading.value, str)
        and heading.value.strip().casefold() == "checklist review"
    )


def validate_scope(original, updated):
    allowed = {
        "_current_review_filter_page",
        "_current_review_filter_place_panel",
        "_current_review_filter_render",
        "render_checklist_review_page",
    }

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in allowed
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside the panel and review functions."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid visibility patch marker.")


def patch_application(source):
    if MARKER in source:
        return source

    tree = ast.parse(source)

    wrapper = find_function(tree, "_current_review_filter_page")
    renderer = find_function(tree, "_current_review_filter_render")
    review = find_function(tree, "render_checklist_review_page")

    find_function(tree, "_current_review_filter_trace")

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_current_review_filter_place_panel"
        for node in tree.body
    ):
        raise ValueError(
            "The panel-placement helper already exists without "
            "the expected marker."
        )

    # The diagnostic wrapper must still surround the review page.
    if not any(
        isinstance(decorator, ast.Name)
        and decorator.id == "_current_review_filter_page"
        for decorator in review.decorator_list
    ):
        raise ValueError(
            "The review diagnostic decorator is missing. "
            "Apply scripts/current-filter.py first."
        )

    expanders = [
        node
        for node in ast.walk(renderer)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "expander"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "Current Review Filters"
        )
    ]

    if len(expanders) != 1:
        raise ValueError(
            "Could not uniquely identify the Current Review Filters panel."
        )

    expander = expanders[0]

    expanded_keyword = next(
        (
            keyword
            for keyword in expander.keywords
            if keyword.arg == "expanded"
        ),
        None,
    )

    if expanded_keyword is None:
        expander.keywords.append(
            ast.keyword(
                arg="expanded",
                value=ast.Constant(value=False),
            )
        )
    else:
        expanded_keyword.value = ast.Constant(value=False)

    header_positions = [
        index
        for index, statement in enumerate(review.body)
        if is_review_header(statement)
    ]

    if len(header_positions) != 1:
        raise ValueError(
            "Could not uniquely identify the Checklist Review header "
            "in the review function. Application was not changed."
        )

    review.body.insert(
        header_positions[0] + 1,
        ast.Expr(
            value=ast.Call(
                func=ast.Name(
                    id="_current_review_filter_place_panel",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        ),
    )

    edits = []

    for function in (renderer, review):
        # Include decorators when replacing the original function text.
        start_line = min(
            [function.lineno]
            + [
                decorator.lineno
                for decorator in function.decorator_list
            ]
        )

        end_line = function.end_lineno
        ast.fix_missing_locations(function)

        edits.append(
            (
                start_line - 1,
                end_line,
                ast.unparse(function) + "\n\n",
            )
        )

    if wrapper.decorator_list:
        raise ValueError(
            "Unexpected decorators on the diagnostic wrapper."
        )

    edits.append(
        (
            wrapper.lineno - 1,
            wrapper.end_lineno,
            REPLACEMENT_WRAPPER.strip("\n") + "\n\n",
        )
    )

    ordered = sorted(edits, key=lambda item: item[0])

    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Overlapping function replacements detected.")

    lines = source.splitlines(keepends=True)

    for start, end, replacement in reversed(ordered):
        lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(updated, "<current-filter-visibility>", "exec")
    validate_scope(source, updated)

    return updated


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Collapse Current Review Filters by default and position "
            "it immediately below the Checklist Review header."
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
        print(f"The visibility update is already installed: {app_path}")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-current-filter-visibility.bak"
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
    print("Current Review Filters is now collapsed by default.")
    print("The panel is positioned directly below the review header.")
    print("Filter logic, records, and diagnostic counts are unchanged.")
    print("Restart or redeploy the app, then reload Checklist Review.")
    print("Interactive visual testing is still required.")


if __name__ == "__main__":
    main()
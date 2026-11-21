# scripts/fix-paging-issue.py
#
# Fixes:
# TypeError: unsupported operand type(s) for -:
# 'NoneType' and 'int'
#
# Repairs Checklist Review pagination at three levels:
#   1. Normalize restored state before evaluating widget defaults.
#   2. Prevent an empty numeric widget from returning None to paging.
#   3. Make get_paginated_items handle invalid page numbers safely.
#
# Supports the previous saved-filter pagination patch.
# Preserves the no-competing-default behavior.
#
# Does not change database records, filters, menu permissions,
# checklist update logic, or prize calculations.
#
# Creates a timestamped source backup.
#
# Stop Streamlit before running:
#
# python scripts/fix-paging-issue.py app.py

RUNTIME = r'''
# CHECKLIST_PAGING_NONE_FIX_V2

def _hcfp_int(value, default=1):
    import math

    try:
        if isinstance(value, bool):
            return int(default)

        number = float(value)

        return (
            int(number)
            if math.isfinite(number)
            else int(default)
        )

    except (TypeError, ValueError, OverflowError):
        return int(default)


def _hcfp_page(value, total_pages, fallback=1):
    maximum = max(
        1,
        _hcfp_int(total_pages, 1),
    )

    return min(
        maximum,
        max(
            1,
            _hcfp_int(
                value,
                _hcfp_int(fallback, 1),
            ),
        ),
    )


def _hcfp_prepare_state(owner_id, total_pages):
    logical_key = saved_filter_key(
        owner_id,
        "page_number",
    )

    input_key = saved_filter_key(
        owner_id,
        "page_number_input",
    )

    logical = _hcfp_page(
        st.session_state.get(logical_key),
        total_pages,
    )

    # This is the backing pagination value, not the widget key.
    st.session_state[logical_key] = logical

    # Only normalize an existing widget value before it is rendered.
    if input_key in st.session_state:
        current = st.session_state[input_key]

        normalized = _hcfp_page(
            current,
            total_pages,
            logical,
        )

        if (
            type(current) is not int
            or current != normalized
        ):
            st.session_state[input_key] = normalized


def _hcfp_resolve_page(value, owner_id, total_pages):
    logical = st.session_state.get(
        saved_filter_key(
            owner_id,
            "page_number",
        ),
        1,
    )

    widget = st.session_state.get(
        saved_filter_key(
            owner_id,
            "page_number_input",
        )
    )

    fallback = _hcfp_page(
        widget,
        total_pages,
        logical,
    )

    return _hcfp_page(
        value,
        total_pages,
        fallback,
    )


def _hcfp_number_input(*args, **kwargs):
    import inspect

    bound = inspect.signature(
        st.number_input
    ).bind_partial(*args, **kwargs)

    key = bound.arguments.get("key")
    minimum = bound.arguments.get("min_value")
    maximum = bound.arguments.get("max_value")

    default = bound.arguments.get(
        "value",
        minimum,
    )

    fallback = _hcfp_int(
        default,
        _hcfp_int(minimum, 1),
    )

    candidate = (
        st.session_state.get(key, fallback)
        if key is not None
        else fallback
    )

    candidate = _hcfp_int(
        candidate,
        fallback,
    )

    if minimum is not None:
        candidate = max(
            int(minimum),
            candidate,
        )

    if maximum is not None:
        candidate = min(
            int(maximum),
            candidate,
        )

    if key is not None and key in st.session_state:
        current = st.session_state[key]

        if (
            type(current) is not int
            or current != candidate
        ):
            st.session_state[key] = candidate

        # Session State provides the current value.
        # Avoid declaring a competing widget default.
        bound.arguments["value"] = None

    result = st.number_input(
        *bound.args,
        **bound.kwargs,
    )

    # An empty widget must never propagate None to pagination.
    # Do not modify the widget's Session State after rendering.
    result = _hcfp_int(
        result,
        candidate,
    )

    if minimum is not None:
        result = max(
            int(minimum),
            result,
        )

    if maximum is not None:
        result = min(
            int(maximum),
            result,
        )

    return result


def get_paginated_items(items, page_number, page_size):
    if (
        isinstance(page_size, str)
        and page_size.strip().casefold() == "show all"
    ):
        return items

    size = _hcfp_int(
        page_size,
        50,
    )

    # Preserve the existing nonpositive-size "show all" behavior.
    if size <= 0:
        return items

    total_pages = max(
        1,
        (len(items) + size - 1) // size,
    )

    page = _hcfp_page(
        page_number,
        total_pages,
    )

    start_index = (page - 1) * size

    return items[
        start_index:start_index + size
    ]

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# CHECKLIST_PAGING_NONE_FIX_V2"


def is_numeric_widget(node):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "st"
        and node.attr == "number_input"
    ) or (
        isinstance(node, ast.Name)
        and node.id == "_sfi_page_number_input"
    )


class FixReviewPaging(ast.NodeTransformer):
    def __init__(self):
        self.count = 0

    def visit_Assign(self, node):
        if not any(
            isinstance(target, ast.Name)
            and target.id == "current_page"
            for target in node.targets
        ):
            return self.generic_visit(node)

        call = node.value

        if not isinstance(call, ast.Call):
            return self.generic_visit(node)

        key = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "key"
            ),
            None,
        )

        if key is None or not any(
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and (
                item.value == "page_number_input"
                or item.value.endswith(
                    "_page_number_input"
                )
            )
            for item in ast.walk(key)
        ):
            return self.generic_visit(node)

        if is_numeric_widget(call.func):
            call.func = ast.Name(
                id="_hcfp_number_input",
                ctx=ast.Load(),
            )

        elif (
            call.args
            and is_numeric_widget(call.args[0])
        ):
            call.args[0] = ast.Name(
                id="_hcfp_number_input",
                ctx=ast.Load(),
            )

        else:
            raise ValueError(
                "Unrecognized page-number widget wrapper."
            )

        before = ast.parse(
            "_hcfp_prepare_state("
            "owner_id, total_pages)"
        ).body[0]

        after = ast.parse(
            "current_page = _hcfp_resolve_page("
            "current_page, owner_id, total_pages)"
        ).body[0]

        self.count += 1

        return [
            before,
            node,
            after,
        ]


def start_line(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


def patch_source(source):
    tree = ast.parse(source)

    if MARKER in source:
        if not any(
            isinstance(node, ast.FunctionDef)
            and node.name == "_hcfp_number_input"
            for node in tree.body
        ):
            raise ValueError(
                "The patch marker exists "
                "without its required helper."
            )

        return source, 0

    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    ]

    if any(
        node.name.startswith("_hcfp_")
        for node in functions
    ):
        raise ValueError(
            "Conflicting pagination helpers already exist."
        )

    paginators = [
        node
        for node in functions
        if node.name == "get_paginated_items"
    ]

    if len(paginators) != 1:
        raise ValueError(
            "Expected one get_paginated_items function."
        )

    old = paginators[0]

    if (
        [
            argument.arg
            for argument in old.args.args
        ] != [
            "items",
            "page_number",
            "page_size",
        ]
        or old.decorator_list
    ):
        raise ValueError(
            "Unexpected paginator signature or decorators."
        )

    if not any(
        node.name == "saved_filter_key"
        for node in functions
    ):
        raise ValueError(
            "Cannot find saved_filter_key."
        )

    edits = []
    visitor = FixReviewPaging()

    for function in functions:
        if function is old:
            continue

        previous = visitor.count
        visitor.visit(function)

        if visitor.count != previous:
            ast.fix_missing_locations(function)

            edits.append(
                (
                    start_line(function),
                    function.end_lineno,
                    ast.unparse(function) + "\n\n",
                )
            )

    if not visitor.count:
        raise ValueError(
            "Cannot identify the Checklist Review "
            "page-number widget. "
            "No changes were made."
        )

    helpers = ast.parse(RUNTIME).body

    position = tree.body.index(old)
    tree.body[position:position + 1] = helpers

    edits.append(
        (
            start_line(old),
            old.end_lineno,
            RUNTIME.strip() + "\n\n",
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

    for begin, end, replacement in reversed(edits):
        lines[begin:end] = [replacement]

    updated = "".join(lines)

    compile(
        updated,
        "<checklist-paging-fix>",
        "exec",
    )

    if ast.dump(
        ast.parse(updated),
        include_attributes=False,
    ) != ast.dump(
        tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected source changes outside "
            "the intended pagination fix."
        )

    return updated, visitor.count


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fix None page numbers "
            "in Checklist Review."
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
        updated, count = patch_source(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}"
        ) from error

    if not count:
        print(
            "The Checklist Review paging fix "
            "is already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-paging-fix-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed "
                "during validation. Retry."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Backup verification failed."
            )

        encoding = (
            "utf-8-sig"
            if original.startswith(b"\xef\xbb\xbf")
            else "utf-8"
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="\n",
            dir=app.parent,
            prefix=f".{app.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated)

        shutil.copymode(app, temporary)

        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed "
                "before replacement. Retry."
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
    print(
        "Patched review pagination widget(s): "
        f"{count}"
    )
    print(
        "Empty page inputs now fall back "
        "to a valid page number."
    )
    print(
        "Restored page state is normalized before "
        "widget defaults are evaluated."
    )
    print(
        "The paginator also handles invalid "
        "or out-of-range page numbers safely."
    )
    print(
        "No database records, filters, menu permissions, "
        "or prize calculations were changed."
    )
    print(
        "Restart Streamlit and reopen Checklist Review."
    )


if __name__ == "__main__":
    main()
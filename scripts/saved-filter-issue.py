# scripts/saved-filter-issue.py
#
# Fixes:
# The widget with key "saved_filter_..._page_number_input"
# was created with a default value but also had its value
# set via the Session State API.
#
# Applies only to saved-filter pagination.
# Supports direct st.number_input calls and calls passed through
# review_stable_numeric_filter_input.
#
# Preserves restored state without declaring a competing default.
# Constrains restored page numbers to the current valid range.
#
# Does not suppress warnings globally.
# Does not change database records, saved filters, or update logic.
# Creates a timestamped source backup.
#
# Stop Streamlit before running:
#
# python scripts/saved-filter-issue.py app.py

RUNTIME = r'''
# SAVED_FILTER_PAGE_NUMBER_STATE_FIX_V1

def _sfi_page_number_input(*args, **kwargs):
    import inspect
    import math

    bound = inspect.signature(
        st.number_input
    ).bind_partial(*args, **kwargs)

    key = bound.arguments.get("key")

    if key is not None and key in st.session_state:
        minimum = bound.arguments.get("min_value")
        maximum = bound.arguments.get("max_value")

        fallback = bound.arguments.get(
            "value",
            minimum,
        )

        if fallback is None or fallback == "min":
            fallback = (
                minimum
                if minimum is not None
                else 1
            )

        def page_number(value, default):
            try:
                if isinstance(value, bool):
                    raise ValueError(
                        "Boolean page number"
                    )

                number = float(value)

                if not math.isfinite(number):
                    raise ValueError(
                        "Non-finite page number"
                    )

                return int(number)

            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                return int(default)

        current = st.session_state[key]

        normalized = page_number(
            current,
            fallback,
        )

        if minimum is not None:
            normalized = max(
                int(minimum),
                normalized,
            )

        if maximum is not None:
            normalized = min(
                int(maximum),
                normalized,
            )

        # Normalize only before the widget is instantiated.
        if (
            type(current) is not int
            or current != normalized
        ):
            st.session_state[key] = normalized

        # Session State owns the current value.
        # Explicit None avoids declaring a competing default.
        # Simply omitting value would leave the implicit "min" default.
        bound.arguments["value"] = None

    return st.number_input(
        *bound.args,
        **bound.kwargs,
    )

'''

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# SAVED_FILTER_PAGE_NUMBER_STATE_FIX_V1"
HELPER = "_sfi_page_number_input"


def saved_page_key(node):
    parts = [
        item.value
        for item in ast.walk(node)
        if (
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
        )
    ]

    page = any(
        part == "page_number_input"
        or part.endswith("_page_number_input")
        for part in parts
    )

    saved = (
        any(
            part.startswith("saved_filter_")
            for part in parts
        )
        or any(
            isinstance(item, ast.Name)
            and item.id == "saved_filter_key"
            for item in ast.walk(node)
        )
    )

    return page and saved


def number_input(node):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "st"
        and node.attr == "number_input"
    )


def patch_source(source):
    tree = ast.parse(source)

    existing = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == HELPER
        )
    ]

    if MARKER in source:
        if len(existing) != 1:
            raise ValueError(
                "Installation marker exists without "
                "the expected helper."
            )

        return source, 0

    if existing:
        raise ValueError(
            "A conflicting page-number helper already exists."
        )

    mains = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "main"
        )
    ]

    if len(mains) != 1:
        raise ValueError(
            "Cannot uniquely identify "
            "the application main function."
        )

    main = mains[0]

    encoded = source.encode("utf-8")

    # AST column offsets use UTF-8 byte offsets.
    offsets = [0]

    for line in encoded.splitlines(keepends=True):
        offsets.append(
            offsets[-1] + len(line)
        )

    edits = []
    count = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        key = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "key"
            ),
            None,
        )

        if (
            key is None
            or not saved_page_key(key)
        ):
            continue

        if number_input(node.func):
            node.func = ast.Name(
                id=HELPER,
                ctx=ast.Load(),
            )

        elif (
            node.args
            and number_input(node.args[0])
        ):
            node.args[0] = ast.Name(
                id=HELPER,
                ctx=ast.Load(),
            )

        else:
            continue

        ast.fix_missing_locations(node)

        begin = (
            offsets[node.lineno - 1]
            + node.col_offset
        )

        end = (
            offsets[node.end_lineno - 1]
            + node.end_col_offset
        )

        edits.append(
            (
                begin,
                end,
                ast.unparse(node).encode("utf-8"),
            )
        )

        count += 1

    if not count:
        raise ValueError(
            "Cannot identify the saved-filter "
            "page-number number_input call. "
            "No changes were made."
        )

    helpers = ast.parse(RUNTIME).body

    index = tree.body.index(main)
    tree.body[index:index] = helpers

    first_line = min(
        [main.lineno]
        + [
            decorator.lineno
            for decorator in main.decorator_list
        ]
    )

    position = offsets[first_line - 1]

    edits.append(
        (
            position,
            position,
            (
                RUNTIME.strip() + "\n\n"
            ).encode("utf-8"),
        )
    )

    edits.sort(
        key=lambda edit: (
            edit[0],
            edit[1],
        )
    )

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

    for begin, end, replacement in reversed(edits):
        encoded = (
            encoded[:begin]
            + replacement
            + encoded[end:]
        )

    updated = encoded.decode("utf-8")

    compile(
        updated,
        "<saved-filter-page-state-fix>",
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
            "Unexpected changes outside "
            "the intended page-number fix."
        )

    return updated, count


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Fix the saved-filter pagination "
            "Session State/default-value conflict."
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
            "The saved-filter page-number fix "
            "is already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-saved-filter-fix-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application changed during validation. Retry."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
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
                "Application changed before replacement. Retry."
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
        "Patched saved-filter page-number call(s): "
        f"{count}"
    )
    print(
        "Restored pagination now uses Session State "
        "without a competing default."
    )
    print(
        "Page numbers are constrained "
        "to the current valid range."
    )
    print(
        "No global warning suppression "
        "or database changes were added."
    )
    print(
        "Restart Streamlit, then update a checklist "
        "from Checklist Review."
    )


if __name__ == "__main__":
    main()
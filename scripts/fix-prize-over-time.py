# scripts/fix-prize-over-time.py
#
# Requires checklist-review-implementation20261125.py.
#
# Makes Prize over time optional:
#   - Unchecked by default.
#   - Chart and calculations run only when checked.
#   - Preserves existing chart behavior when enabled.
#
# Does not change filters, table sorting, pagination,
# database records, or other charts.
#
# Creates a timestamped source backup.
#
# Stop Streamlit before running:
#
# python scripts/fix-prize-over-time.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# PRIZE_OVER_TIME_OPTIONAL_V1"
FUNCTION_NAME = "_crp_render_trend"

PREFIX = """
_crp_show_trend = st.checkbox(
    "Show prize over time",
    value=False,
    key=f"review_prize_over_time_visible_{owner_id}",
)
if not _crp_show_trend:
    return
"""


def patch_source(source):
    tree = ast.parse(source)

    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == FUNCTION_NAME
    ]

    if len(functions) != 1:
        raise ValueError(
            f"Expected one {FUNCTION_NAME} function. "
            "Install checklist-review-implementation20261125.py "
            "before applying this patch."
        )

    function = functions[0]

    if MARKER in source:
        return source, False

    arguments = {
        argument.arg
        for argument in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
        )
    }

    if "owner_id" not in arguments:
        raise ValueError(
            "The prize chart does not have the expected "
            "owner_id argument."
        )

    if any(
        isinstance(node, ast.Name)
        and node.id == "_crp_show_trend"
        for node in ast.walk(function)
    ):
        raise ValueError(
            "A conflicting prize-chart visibility control "
            "already exists."
        )

    start = min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1

    end = function.end_lineno

    # Keep an existing function docstring as the first statement.
    insertion = 0

    if (
        function.body
        and isinstance(function.body[0], ast.Expr)
        and isinstance(function.body[0].value, ast.Constant)
        and isinstance(function.body[0].value.value, str)
    ):
        insertion = 1

    function.body[insertion:insertion] = ast.parse(
        PREFIX
    ).body

    ast.fix_missing_locations(function)

    replacement = (
        MARKER
        + "\n"
        + ast.unparse(function)
        + "\n\n"
    )

    lines = source.splitlines(keepends=True)
    lines[start:end] = [replacement]

    updated = "".join(lines)

    compile(
        updated,
        "<optional-prize-over-time>",
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
            "Unexpected changes outside the intended "
            "chart-visibility update."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Make Prize over time visible only "
            "when its checkbox is checked."
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
        updated, changed = patch_source(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "The optional Prize over time control "
            "is already installed."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-optional-prize-trend-{timestamp}.bak"
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
        "Prize over time now starts unchecked."
    )
    print(
        "Chart rendering and calculations run "
        "only when checked."
    )
    print(
        "Other Checklist Review behavior was preserved."
    )
    print(
        "Restart Streamlit to apply the change."
    )


if __name__ == "__main__":
    main()
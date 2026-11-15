# scripts/change-results-size-per-page-in-prize-a-month.py
#
# Sets the default chart view size to 50 for:
#   - Jockey prize comparison
#   - Horse-owner prize comparison
#   - Trainer prize comparison
#
# Updates both:
#   - JavaScript initial pageSize
#   - Selected option in the Bars per view control
#
# Preserves existing 8/12/20/50/100 options.
# Shows all available names when fewer than 50 exist.
#
# Does not change calculations, filters, date ranges,
# styling, tables, exports, or database records.
#
# Creates a timestamped source backup.
#
# Stop Streamlit before running:
#
# python scripts/change-results-size-per-page-in-prize-a-month.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile


FUNCTION_NAME = "_mct_chart"
DEFAULT_SIZE = 50


def update_chart_html(html):
    declaration = re.compile(
        r"(\b(?:let|const|var)\s+pageSize\s*=\s*)"
        r"\d+"
        r"(\s*;)"
    )

    if len(list(declaration.finditer(html))) != 1:
        raise ValueError(
            "Cannot uniquely identify the chart's "
            "initial pageSize declaration."
        )

    updated = declaration.sub(
        lambda match: (
            match.group(1)
            + str(DEFAULT_SIZE)
            + match.group(2)
        ),
        html,
        count=1,
    )

    select_pattern = re.compile(
        r"""(<select\b[^>]*\bid\s*=\s*["']pageSize["'][^>]*>)"""
        r"(.*?)"
        r"(</select\s*>)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    selects = list(select_pattern.finditer(updated))

    if len(selects) != 1:
        raise ValueError(
            "Cannot uniquely identify the Bars per view control."
        )

    option_pattern = re.compile(
        r"<option\b([^>]*)>(.*?)</option\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    option_matches = list(
        option_pattern.finditer(
            selects[0].group(2)
        )
    )

    matching_options = [
        match
        for match in option_matches
        if match.group(2).strip() == str(DEFAULT_SIZE)
    ]

    if len(matching_options) != 1:
        raise ValueError(
            "Expected exactly one 50-bar option. "
            "Install the preceding prize UI updates first."
        )

    selected_attribute = re.compile(
        r"""\s+selected(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?""",
        flags=re.IGNORECASE,
    )

    def replace_option(match):
        attributes = selected_attribute.sub(
            "",
            match.group(1),
        )

        text = match.group(2)

        if text.strip() == str(DEFAULT_SIZE):
            attributes += " selected"

        return (
            "<option"
            + attributes
            + ">"
            + text
            + "</option>"
        )

    def replace_select(match):
        options = option_pattern.sub(
            replace_option,
            match.group(2),
        )

        return (
            match.group(1)
            + options
            + match.group(3)
        )

    return select_pattern.sub(
        replace_select,
        updated,
        count=1,
    )


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
            f"Expected one {FUNCTION_NAME} function; "
            f"found {len(functions)}."
        )

    function = functions[0]

    html_assignments = [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "html"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]

    if len(html_assignments) != 1:
        raise ValueError(
            "Cannot uniquely identify the chart HTML."
        )

    html_node = html_assignments[0].value
    original_html = html_node.value
    updated_html = update_chart_html(original_html)

    if updated_html == original_html:
        return source, False

    html_node.value = updated_html

    ast.fix_missing_locations(function)

    start = min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1

    lines = source.splitlines(keepends=True)

    lines[start:function.end_lineno] = [
        ast.unparse(function) + "\n\n"
    ]

    updated = "".join(lines)

    compile(
        updated,
        "<prize-default-view-size>",
        "exec",
    )

    # Confirm the rewritten application matches the intended AST,
    # including all unrelated functions and statements.
    if ast.dump(
        ast.parse(updated),
        include_attributes=False,
    ) != ast.dump(
        tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes outside the intended "
            "chart HTML update."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Set the default prize-comparison "
            "chart view size to 50."
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
            "The default prize chart view size "
            "is already 50. No changes were made."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-prize-default-50-{timestamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed during validation. "
                "Run the patch again."
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
                "Application source changed before replacement. "
                "Run the patch again."
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
    print("Syntax and intended-change validation passed.")
    print(
        "Default bars per view: 50 "
        "for jockey, horse-owner, and trainer pages."
    )
    print(
        "Existing 8/12/20/50/100 options were preserved."
    )
    print(
        "Calculations, styling, and database records "
        "were not changed."
    )
    print("Restart Streamlit to apply the new default.")


if __name__ == "__main__":
    main()
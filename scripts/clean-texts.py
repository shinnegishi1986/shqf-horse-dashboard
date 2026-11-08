# scripts/clean-texts.py
#
# Removes only the two requested explanatory captions.
# Keeps filter history, recency metrics, and all other behavior unchanged.
# Application context: [1]
#
# Run:
#   python scripts/clean-texts.py
#
# Or specify the application file:
#   python scripts/clean-texts.py app.py

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


HISTORY_TEXT_PREFIX = (
    "Filter changes are remembered automatically in this session. "
    "Last Filter goes back; Next Filter goes forward. "
    "Changing a past configuration replaces its forward history. "
    "Pagination does not create history entries. "
    "Up to "
)

HISTORY_TEXT_SUFFIX = " configurations are retained."

TOP_THREE_TEXT = (
    "Top-3 means finishing position 1, 2, or 3. "
    "The latest matched date uses all actual filtered results, "
    "before pagination. Days since the latest match uses the "
    "application server's current date. "
    "This indicates recency, not a reliability score."
)


def normalize_text(value):
    return " ".join(value.split())


def get_caption_text(node, constants):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.JoinedStr):
        parts = []

        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)

            elif isinstance(part, ast.FormattedValue):
                if not (
                    isinstance(part.value, ast.Name)
                    and part.value.id == "FILTER_HISTORY_LIMIT"
                    and part.value.id in constants
                    and part.conversion == -1
                    and part.format_spec is None
                ):
                    return None

                parts.append(str(constants[part.value.id]))

            else:
                return None

        return "".join(parts)

    return None


def is_requested_caption(text):
    text = normalize_text(text)

    if text == normalize_text(TOP_THREE_TEXT):
        return True

    prefix = normalize_text(HISTORY_TEXT_PREFIX) + " "
    suffix = " " + normalize_text(HISTORY_TEXT_SUFFIX)

    if text.startswith(prefix) and text.endswith(suffix):
        limit = text[len(prefix):-len(suffix)]
        return limit.isdecimal()

    return False


def clean_application(source):
    tree = ast.parse(source)

    constants = {}

    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int
        ):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "FILTER_HISTORY_LIMIT"
                ):
                    constants[target.id] = node.value.value

    removals = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue

        call = node.value

        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "caption"
        ):
            continue

        text_argument = call.args[0] if call.args else None

        if text_argument is None:
            text_argument = next(
                (
                    keyword.value
                    for keyword in call.keywords
                    if keyword.arg == "body"
                ),
                None,
            )

        text = get_caption_text(text_argument, constants)

        if text is not None and is_requested_caption(text):
            removals.append((node.lineno - 1, node.end_lineno))

    if not removals:
        return source, 0

    lines = source.splitlines(keepends=True)

    for start, end in sorted(removals, reverse=True):
        del lines[start:end]

    updated = "".join(lines)

    compile(updated, "<clean-texts>", "exec")

    return updated, len(removals)


def main():
    parser = argparse.ArgumentParser(
        description="Remove the two requested Checklist Review captions."
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

    try:
        updated, removed_count = clean_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    if removed_count == 0:
        print(f"No matching captions found in: {app_path}")
        print("They may already have been removed.")
        return

    backup_path = app_path.with_name(
        f"{app_path.name}.before-clean-texts.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before running this script."
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
    print(f"Removed {removed_count} matching caption(s).")
    print("Python syntax validation passed.")
    print("Filter history and top-three recency metrics remain unchanged.")
    print("Reload or redeploy the application to see the changes.")


if __name__ == "__main__":
    main()
# scripts/fix-horse-template-installer.py
#
# Repairs the previously supplied scripts/add-horse-template.py.
# Accepts the widget-key expressions used in your uploaded app:
#
# registration_key("selected_horse_idx") + "_accept_name"
#
# Does not rename widget keys or alter the feature's runtime code.
# After repairing the installer, runs it against the application.
#
# Keep the original add-horse-template.py in this script's folder.
#
# Stop Streamlit before running:
#
# python scripts/fix-horse-template-installer.py app.py

import argparse
import ast
import inspect
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap


MARKER = "# HORSE_TEMPLATE_INSTALLER_KEY_FIX_V1"
FEATURE_MARKER = "# HORSE_PROFILE_TEMPLATES_V1"

ERROR_MESSAGE = (
    "Expected revision-aware registration_key widget keys."
)

FIELDS = {
    "selected_horse_idx",
    "selected_horse_owner_idx",
    "selected_stallion_idx",
    "selected_broodmare_sire_idx",
    "selected_trainer_idx",
}


def _ht_key_expression_supported(expression, field_name):
    if isinstance(expression, ast.BinOp):
        if not (
            isinstance(expression.op, ast.Add)
            and isinstance(expression.right, ast.Constant)
            and expression.right.value == "_accept_name"
        ):
            return False

        expression = expression.left
        allowed = {field_name}

    else:
        allowed = {
            field_name,
            field_name + "_accept_name",
        }

    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "registration_key"
        and len(expression.args) == 1
        and not expression.keywords
        and isinstance(expression.args[0], ast.Constant)
        and isinstance(expression.args[0].value, str)
        and expression.args[0].value in allowed
    )


def verify_app(source):
    tree = ast.parse(source)

    functions = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "render_race_checklist_page"
        )
    ]

    if len(functions) != 1:
        raise ValueError(
            "Cannot uniquely identify "
            "render_race_checklist_page."
        )

    found = set()

    for node in ast.walk(functions[0]):
        if (
            not isinstance(node, ast.Assign)
            or not isinstance(node.value, ast.Call)
        ):
            continue

        for target in node.targets:
            if (
                not isinstance(target, ast.Name)
                or target.id not in FIELDS
            ):
                continue

            key = next(
                (
                    keyword.value
                    for keyword in node.value.keywords
                    if keyword.arg == "key"
                ),
                None,
            )

            if (
                key is None
                or not _ht_key_expression_supported(
                    key,
                    target.id,
                )
            ):
                raise ValueError(
                    "Unrecognized widget key for "
                    f"{target.id}."
                )

            found.add(target.id)

    if found != FIELDS:
        raise ValueError(
            "Cannot verify all five "
            "horse-reference widget keys."
        )


def repair_installer(source):
    tree = ast.parse(source)

    if MARKER in source:
        if not any(
            isinstance(node, ast.FunctionDef)
            and node.name == "_ht_key_expression_supported"
            for node in tree.body
        ):
            raise ValueError(
                "Repair marker exists without its helper."
            )

        return source, False

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_ht_key_expression_supported"
        for node in tree.body
    ):
        raise ValueError(
            "Conflicting installer key validator "
            "already exists."
        )

    functions = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "patch_source"
        )
    ]

    if len(functions) != 1:
        raise ValueError(
            "Expected patch_source in the original "
            "add-horse-template.py installer."
        )

    function = functions[0]

    guards = [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.If)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Raise)
            and any(
                isinstance(item, ast.Constant)
                and item.value == ERROR_MESSAGE
                for item in ast.walk(node.body[0])
            )
        )
    ]

    if len(guards) != 1:
        raise ValueError(
            "Cannot identify the exact failed "
            "installer validation guard."
        )

    guard = guards[0]

    guard.test = ast.parse(
        "not _ht_key_expression_supported(key, name)",
        mode="eval",
    ).body

    ast.fix_missing_locations(guard)

    helper_source = inspect.getsource(
        _ht_key_expression_supported
    )

    helper = ast.parse(helper_source).body[0]

    position = tree.body.index(function)
    tree.body.insert(position, helper)

    lines = source.splitlines(keepends=True)

    original_line = lines[guard.lineno - 1]

    indent = original_line[
        :len(original_line)
        - len(original_line.lstrip())
    ]

    first = min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1

    edits = [
        (
            guard.lineno - 1,
            guard.end_lineno,
            textwrap.indent(
                ast.unparse(guard),
                indent,
            ) + "\n",
        ),
        (
            first,
            first,
            MARKER
            + "\n"
            + helper_source.strip()
            + "\n\n",
        ),
    ]

    for begin, end, replacement in sorted(
        edits,
        reverse=True,
    ):
        lines[begin:end] = [replacement]

    updated = "".join(lines)

    compile(
        updated,
        "<repaired-horse-template-installer>",
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
            "the installer's key validation."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Repair horse-template key validation, "
            "then run the original feature installer."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    parser.add_argument(
        "--installer",
        default=str(
            Path(__file__).resolve().with_name(
                "add-horse-template.py"
            )
        ),
    )

    args = parser.parse_args()

    app = Path(args.app_file).resolve()
    installer = Path(args.installer).resolve()

    try:
        app_source = app.read_bytes().decode(
            "utf-8-sig"
        )

        if FEATURE_MARKER in app_source:
            print(
                "Horse templates are already "
                "installed in this app."
            )
            return

        verify_app(app_source)

        original = installer.read_bytes()

        updated, changed = repair_installer(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}"
        ) from error

    if changed:
        stamp = datetime.now().strftime(
            "%Y%m%d-%H%M%S-%f"
        )

        backup = installer.with_name(
            f"{installer.name}."
            f"before-key-fix-{stamp}.bak"
        )

        temporary = None

        try:
            if installer.read_bytes() != original:
                raise RuntimeError(
                    "Installer changed during validation. "
                    "Retry."
                )

            shutil.copy2(installer, backup)

            if backup.read_bytes() != original:
                raise RuntimeError(
                    "Installer backup verification failed."
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
                dir=installer.parent,
                prefix=f".{installer.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(updated)

            shutil.copymode(
                installer,
                temporary,
            )

            if installer.read_bytes() != original:
                raise RuntimeError(
                    "Installer changed before replacement. "
                    "Retry."
                )

            temporary.replace(installer)
            temporary = None

        finally:
            if (
                temporary is not None
                and temporary.exists()
            ):
                temporary.unlink()

        print(
            f"Repaired installer: {installer}",
            flush=True,
        )

        print(
            f"Installer backup: {backup}",
            flush=True,
        )

    print(
        "All five uploaded-style widget keys verified. "
        "Running the horse-template installer...",
        flush=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(installer),
            str(app),
        ],
        check=False,
    )

    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
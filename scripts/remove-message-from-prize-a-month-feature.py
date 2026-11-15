# scripts/remove-message-from-prize-a-month-feature.py
#
# Removes only:
# "Many names are selected. Narrow the selection for a more readable chart."
#
# Applies to the shared prize-comparison page function, covering:
#   - Jockey
#   - Horse Owner
#   - Trainer
#
# Does not change charts, calculations, selections, pagination,
# date ranges, database records, or other validation messages.
#
# Creates a timestamped source backup.
#
# Stop Streamlit before running:
#
# python scripts/remove-message-from-prize-a-month-feature.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


TARGET_FUNCTION = "_mc_page"

TARGET_MESSAGE = (
    "Many names are selected. "
    "Narrow the selection for a more readable chart."
)


class RemoveMessage(ast.NodeTransformer):
    def __init__(self):
        self.removed = 0

    def visit_Expr(self, node):
        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
            and call.func.attr == "warning"
        ):
            message = (
                call.args[0]
                if call.args
                else next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "body"
                    ),
                    None,
                )
            )

            if (
                isinstance(message, ast.Constant)
                and message.value == TARGET_MESSAGE
            ):
                self.removed += 1
                return None

        return self.generic_visit(node)

    def visit_If(self, node):
        self.generic_visit(node)

        # Remove the condition if its only action was the warning.
        if not node.body:
            if not node.orelse:
                return None

            # Preserve any existing else branch.
            node.body = [ast.Pass()]

        return node


def patch_source(source):
    tree = ast.parse(source)

    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == TARGET_FUNCTION
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one {TARGET_FUNCTION} function; "
            f"found {len(matches)}."
        )

    function = matches[0]

    start = min(
        [function.lineno]
        + [
            decorator.lineno
            for decorator in function.decorator_list
        ]
    ) - 1

    end = function.end_lineno

    transformer = RemoveMessage()
    transformer.visit(function)

    if transformer.removed == 0:
        return source, 0

    ast.fix_missing_locations(function)

    lines = source.splitlines(keepends=True)

    lines[start:end] = [
        ast.unparse(function) + "\n\n"
    ]

    updated = "".join(lines)

    compile(
        updated,
        "<remove-prize-selection-message>",
        "exec",
    )

    def outside_target_function(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name == TARGET_FUNCTION
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if (
        outside_target_function(source)
        != outside_target_function(updated)
    ):
        raise ValueError(
            "Unexpected changes outside the "
            "prize-comparison page function."
        )

    return updated, transformer.removed


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Remove the many-names-selected message "
            "from prize-comparison pages."
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
        updated, removed = patch_source(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    if removed == 0:
        print(
            "The specified message is already absent. "
            "No changes were made."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-remove-prize-message-{timestamp}.bak"
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
    print(f"Removed message occurrence(s): {removed}")
    print("Syntax and change-scope validation passed.")
    print("Charts, data, and pagination were preserved.")
    print("Other validation messages were preserved.")
    print("Restart Streamlit to apply the change.")


if __name__ == "__main__":
    main()
# scripts/change-left-menu-appearance.py
#
# Replaces the main sidebar radio menu with styled navigation buttons.
# Preserves existing menu options, routing, login, and logout.
# Does not change page content, database records, or global theme.
#
# Stop Streamlit before running:
#
# python scripts/change-left-menu-appearance.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# HORSE_CHECKLIST_LEFT_MENU_V1"

RUNTIME = r'''
# HORSE_CHECKLIST_LEFT_MENU_V1

def _hcm_select_page(state_key, page):
    st.session_state[state_key] = page


def _hcm_menu(
    label,
    options,
    index=0,
    format_func=str,
    key=None,
    *,
    disabled=False,
    **kwargs,
):
    pages = list(options)

    if not pages:
        return None

    state_key = key or "app_navigation_page"
    default_index = 0 if index is None else int(index)

    if not 0 <= default_index < len(pages):
        default_index = 0

    active = st.session_state.get(
        state_key,
        pages[default_index],
    )

    if active not in pages:
        active = pages[default_index]

    # Keep the navigation state independent of the removed radio widget.
    st.session_state[state_key] = active

    css = """
    <style>
    .st-key-hc_left_menu {
        gap: 0.3rem !important;
    }

    .st-key-hc_left_menu button {
        width: 100% !important;
        min-height: 44px !important;
        justify-content: flex-start !important;
        text-align: left !important;
        padding: 0.65rem 0.85rem !important;
        border-radius: 10px !important;
        box-shadow: none;
        transition:
            background-color 120ms ease,
            border-color 120ms ease;
    }

    .st-key-hc_left_menu button p {
        width: 100%;
        margin: 0;
        text-align: left !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        line-height: 1.35 !important;
        color: inherit !important;
        overflow-wrap: anywhere;
    }

    .st-key-hc_left_menu button[kind="secondary"],
    .st-key-hc_left_menu button[data-testid="stBaseButton-secondary"] {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: inherit !important;
    }

    .st-key-hc_left_menu button[kind="secondary"]:hover:not(:disabled),
    .st-key-hc_left_menu button[data-testid="stBaseButton-secondary"]:hover:not(:disabled) {
        background: rgba(128, 145, 172, 0.12) !important;
        border-color: rgba(128, 145, 172, 0.2) !important;
    }

    .st-key-hc_left_menu button[kind="primary"],
    .st-key-hc_left_menu button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(
            110deg,
            #234d8b,
            #1d3c6b
        ) !important;
        border: 1px solid #4774b4 !important;
        color: #f5f8ff !important;
        box-shadow: inset 3px 0 0 #a7c7ff !important;
    }

    .st-key-hc_left_menu button[kind="primary"] p,
    .st-key-hc_left_menu button[data-testid="stBaseButton-primary"] p {
        font-weight: 650 !important;
    }

    .st-key-hc_left_menu button:focus-visible {
        outline: 2px solid #7daaff !important;
        outline-offset: 2px !important;
    }

    .st-key-hc_left_menu button:disabled {
        opacity: 0.45;
    }

    @media (prefers-reduced-motion: reduce) {
        .st-key-hc_left_menu button {
            transition: none !important;
        }
    }
    </style>
    """

    formatter = format_func or str

    with st.sidebar.container():
        st.markdown(
            css,
            unsafe_allow_html=True,
        )

        with st.container(key="hc_left_menu"):
            for position, page in enumerate(pages):
                st.button(
                    str(formatter(page)),
                    key=f"hc_menu_{state_key}_{position}",
                    type=(
                        "primary"
                        if page == active
                        else "secondary"
                    ),
                    disabled=disabled,
                    width="stretch",
                    on_click=_hcm_select_page,
                    args=(state_key, page),
                )

    return active

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
            f"Expected one {name}; found {len(matches)}."
        )

    return matches[0]


def definition_start(node):
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
        find_function(tree, "_hcm_menu")
        find_function(tree, "_hcm_select_page")
        return source, False

    existing_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
    }

    if existing_names.intersection(
        {"_hcm_menu", "_hcm_select_page"}
    ):
        raise ValueError(
            "Conflicting navigation helpers already exist."
        )

    main = find_function(tree, "main")

    menu_calls = [
        node
        for node in ast.walk(main)
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "st.sidebar.radio"
        )
    ]

    if len(menu_calls) != 1:
        raise ValueError(
            "Cannot uniquely identify the main sidebar radio menu."
        )

    menu_call = menu_calls[0]

    if (
        len(menu_call.args) < 2
        and not any(
            keyword.arg == "options"
            for keyword in menu_call.keywords
        )
    ):
        raise ValueError(
            "Cannot identify the existing navigation options."
        )

    # Preserve every original option and argument.
    # Only replace the menu renderer.
    menu_call.func = ast.Name(
        id="_hcm_menu",
        ctx=ast.Load(),
    )

    ast.fix_missing_locations(main)

    helpers = ast.parse(RUNTIME).body

    replacement = (
        MARKER
        + "\n"
        + "\n\n".join(
            ast.unparse(node)
            for node in helpers
        )
        + "\n\n"
        + ast.unparse(main)
        + "\n\n"
    )

    lines = source.splitlines(keepends=True)

    lines[
        definition_start(main):main.end_lineno
    ] = [replacement]

    updated = "".join(lines)

    compile(
        updated,
        "<horse-checklist-left-menu>",
        "exec",
    )

    # Validate against the complete intended AST.
    # Existing routing and all unrelated code must remain intact.
    position = tree.body.index(main)
    tree.body[position:position] = helpers

    if ast.dump(
        ast.parse(updated),
        include_attributes=False,
    ) != ast.dump(
        tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Unexpected changes outside the intended menu update."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Replace the sidebar radio menu "
            "with styled navigation buttons."
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
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "The styled sidebar menu is already installed."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}.before-left-menu-{timestamp}.bak"
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
    print("Sidebar radio menu replaced with navigation buttons.")
    print("Existing page options and routing preserved.")
    print("Syntax and intended-change validation passed.")
    print("Restart Streamlit to apply the change.")


if __name__ == "__main__":
    main()
# scripts/grant-privilege-for-shin2.py

import argparse
import ast
import os
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

TITLE = "User Administration"
MARKER = "# SHIN2_USER_ADMIN_V1"

RUNTIME = r'''
# SHIN2_USER_ADMIN_V1
_SHIN2_ADMIN_PAGE = "User Administration"


def _shin2_is_admin(conn):
    owner_id = st.session_state.get("user_id")
    if not st.session_state.get("logged_in") or owner_id is None:
        return False

    return conn.execute(
        "SELECT 1 FROM users WHERE id = ? AND username COLLATE BINARY = ?",
        (owner_id, "shin2"),
    ).fetchone() is not None


def _shin2_admin_options(options):
    from contextlib import closing

    pages = list(options)
    with closing(get_db_connection()) as conn:
        allowed = _shin2_is_admin(conn)

    if allowed:
        pages.append(_SHIN2_ADMIN_PAGE)
    elif st.session_state.get("app_navigation_page") == _SHIN2_ADMIN_PAGE:
        st.session_state.pop("app_navigation_page", None)
    return pages


def _shin2_issue_invitation():
    from contextlib import closing
    import secrets

    with closing(get_db_connection()) as conn, conn:
        if not _shin2_is_admin(conn):
            raise PermissionError("Administrator access required.")

        for _ in range(5):
            code = secrets.token_urlsafe(24)
            result = conn.execute(
                "INSERT INTO invitation_codes (code, used) VALUES (?, 0) "
                "ON CONFLICT(code) DO NOTHING",
                (code,),
            )
            if result.rowcount == 1:
                return code

    raise RuntimeError("Could not generate a unique invitation code. Try again.")


def _shin2_create_user(username, display_name, password):
    from contextlib import closing
    import bcrypt

    username = username.strip()
    display_name = display_name.strip()
    if not username or not display_name:
        raise ValueError("Enter both a username and a display name.")
    if len(username) > 64 or len(display_name) > 120:
        raise ValueError("Use at most 64 characters for the username and 120 for the display name.")
    if any(ord(char) < 32 or ord(char) == 127 for char in username + display_name):
        raise ValueError("Username and display name cannot contain control characters.")
    if username.casefold() == "shin2":
        raise ValueError("That username is reserved.")

    password_bytes = password.encode("utf-8")
    if len(password) < 12 or len(password_bytes) > 72 or "\x00" in password:
        raise ValueError("Use at least 12 characters and at most 72 UTF-8 bytes, with no null characters.")

    with closing(get_db_connection()) as conn, conn:
        if not _shin2_is_admin(conn):
            raise PermissionError("Administrator access required.")

        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")
        result = conn.execute(
            "INSERT INTO users (username, display_name, password) VALUES (?, ?, ?) "
            "ON CONFLICT(username) DO NOTHING",
            (username, display_name, hashed),
        )
        if result.rowcount != 1:
            raise ValueError("That username is already registered.")


def _shin2_render_user_admin():
    from contextlib import closing
    import sqlite3

    with closing(get_db_connection()) as conn:
        if not _shin2_is_admin(conn):
            st.error("Administrator access required.")
            return

    st.header(_SHIN2_ADMIN_PAGE)
    invitation_tab, account_tab = st.tabs(["Invitation codes", "Create user"])

    with invitation_tab:
        st.caption("Each code can be used once on the Register tab.")
        if st.button("Issue invitation code", key="shin2_issue_invitation"):
            try:
                code = _shin2_issue_invitation()
            except (PermissionError, RuntimeError) as error:
                st.error(str(error))
            except sqlite3.Error:
                st.error("The invitation code could not be saved. Try again.")
            else:
                st.success("Invitation code issued. Copy it now; it is shown only on this run.")
                st.code(code, language=None)

    with account_tab:
        st.caption("Accounts created here sign in directly on the Login tab.")
        with st.form("shin2_create_user", clear_on_submit=True):
            username = st.text_input("Username")
            display_name = st.text_input("Display name")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create user")

        if submit:
            if password != confirm:
                st.error("The passwords do not match.")
                return
            try:
                _shin2_create_user(username, display_name, password)
            except (PermissionError, ValueError) as error:
                st.error(str(error))
            except sqlite3.Error:
                st.error("The account could not be saved. Try again.")
            else:
                st.success("Account created. The user can now sign in without an invitation code.")
'''


def patch_source(source):
    tree = ast.parse(source)
    if MARKER in source:
        return source

    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if "get_db_connection" not in functions:
        raise ValueError("Could not find get_db_connection().")
    if any(name.startswith("_shin2_") for name in functions):
        raise ValueError("Conflicting administrator helpers already exist.")
    if any(
        isinstance(node, ast.Constant) and node.value == TITLE
        for node in ast.walk(tree)
    ):
        raise ValueError("A User Administration label already exists.")

    mains = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    if len(mains) != 1:
        raise ValueError("Expected exactly one main() function.")
    main = mains[0]

    menus = [
        (index, node)
        for index, node in enumerate(main.body)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) in {"_hcm_menu", "st.sidebar.radio"}
    ]
    if len(menus) != 1:
        raise ValueError("Could not uniquely identify the main sidebar menu.")

    menu_index, assignment = menus[0]
    menu = assignment.value
    page_var = assignment.targets[0].id
    if len(menu.args) >= 2:
        menu.args[1] = ast.Call(
            func=ast.Name(id="_shin2_admin_options", ctx=ast.Load()),
            args=[menu.args[1]], keywords=[],
        )
    else:
        options = [item for item in menu.keywords if item.arg == "options"]
        if len(options) != 1:
            raise ValueError("Could not identify the sidebar options.")
        options[0].value = ast.Call(
            func=ast.Name(id="_shin2_admin_options", ctx=ast.Load()),
            args=[options[0].value], keywords=[],
        )

    logout_positions = [
        index for index, node in enumerate(main.body)
        if isinstance(node, ast.If)
        and any(
            isinstance(call, ast.Call)
            and ast.unparse(call.func) == "st.sidebar.button"
            and any(
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.casefold() == "logout"
                for arg in [*call.args, *(k.value for k in call.keywords if k.arg == "label")]
            )
            for call in ast.walk(node.test)
        )
    ]
    if len(logout_positions) != 1 or logout_positions[0] <= menu_index:
        raise ValueError("Could not locate the logout block after the sidebar menu.")

    route = ast.parse(
        f"if {page_var} == _SHIN2_ADMIN_PAGE:\n"
        "    _shin2_render_user_admin()\n"
        "    return\n"
    ).body[0]
    main.body.insert(logout_positions[0] + 1, route)
    ast.fix_missing_locations(main)

    helpers = ast.parse(RUNTIME).body
    start = min([main.lineno, *(node.lineno for node in main.decorator_list)]) - 1
    lines = source.splitlines(keepends=True)
    lines[start:main.end_lineno] = [
        RUNTIME.strip() + "\n\n" + ast.unparse(main) + "\n"
    ]
    updated = "".join(lines)

    position = tree.body.index(main)
    tree.body[position:position] = helpers
    compile(updated, "<shin2-user-admin>", "exec")
    if ast.dump(ast.parse(updated)) != ast.dump(tree):
        raise ValueError("Validation found changes outside the intended patch.")
    return updated


def cli():
    parser = argparse.ArgumentParser(
        description="Add user administration for the existing shin2 account."
    )
    parser.add_argument("app_file", nargs="?", default="app.py")
    app = Path(parser.parse_args().app_file).resolve()

    try:
        original = app.read_bytes()
        source = original.decode("utf-8-sig")
        updated = patch_source(source)
    except (OSError, ValueError, SyntaxError) as error:
        raise SystemExit(f"Application was not changed: {error}") from error

    if updated == source:
        print("The shin2 administration patch is already installed.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = app.with_name(f"{app.name}.before-shin2-admin-{stamp}.bak")
    temporary = None
    try:
        if app.read_bytes() != original:
            raise RuntimeError("app.py changed during validation. Rerun the patch.")
        shutil.copy2(app, backup)
        if backup.read_bytes() != original:
            raise RuntimeError("Backup verification failed.")

        encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=app.parent, prefix=f".{app.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated.encode(encoding))
        shutil.copymode(app, temporary)
        if app.read_bytes() != original:
            raise RuntimeError("app.py changed before replacement. Rerun the patch.")
        os.replace(temporary, app)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print(f"Updated: {app}")
    print(f"Backup: {backup}")
    print("Restart Streamlit and sign in as shin2 to open User Administration.")


if __name__ == "__main__":
    cli()
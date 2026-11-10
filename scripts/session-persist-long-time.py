# scripts/session-persist-long-time.py
#
# Adds persistent login to the existing username/password application.
#
# Run:
#   python scripts/session-persist-long-time.py app.py
#
# The script creates:
#   1. A patched application file.
#   2. A small local Streamlit component for reading/writing a login cookie.
#
# Deploy the generated _persistent_login_component directory alongside app.py.
#
# Features:
#   - Restores login after browser reloads or Streamlit session resets.
#   - Uses a cryptographically random token.
#   - Stores only the token's SHA-256 digest in SQLite.
#   - Revokes the current browser's token when Logout is pressed.
#   - Invalidates existing tokens after the user's password changes.
#   - Does not put passwords or authentication tokens in URLs.
#
# Limitations:
#   - Browser cookies can be deleted, blocked, or expire.
#   - Private browsing does not provide permanent storage.
#   - Persistent SQLite storage is required across deployments.
#   - This JavaScript-managed cookie cannot be HttpOnly.
#   - Use HTTPS in production. The component sets Secure on HTTPS.
#   - This restores authentication, not unsaved form values or filter history.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


PATCH_MARKER = "# PERSISTENT_LOGIN_DATABASE_TOKEN_V1"


COMPONENT_HTML = r"""<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body>
<script>
(function () {
    "use strict";

    function send(type, extra) {
        var message = {
            isStreamlitMessage: true,
            type: type
        };

        Object.keys(extra || {}).forEach(function (key) {
            message[key] = extra[key];
        });

        window.parent.postMessage(message, "*");
    }

    function readCookie(name) {
        var prefix = encodeURIComponent(name) + "=";
        var parts = document.cookie.split(";");

        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim();

            if (part.indexOf(prefix) === 0) {
                return decodeURIComponent(part.substring(prefix.length));
            }
        }

        return "";
    }

    window.addEventListener("message", function (event) {
        if (event.source !== window.parent) return;

        var message = event.data;

        if (!message || message.type !== "streamlit:render") return;

        var args = message.args || {};
        var name = args.cookie_name;
        var result = {
            request_id: args.request_id,
            token: "",
            error: ""
        };

        try {
            var secure = location.protocol === "https:" ? "; Secure" : "";

            if (args.operation === "set") {
                document.cookie =
                    encodeURIComponent(name) + "=" +
                    encodeURIComponent(args.token) +
                    "; Path=/; SameSite=Lax; Max-Age=34560000" +
                    secure;
            } else if (args.operation === "delete") {
                document.cookie =
                    encodeURIComponent(name) +
                    "=; Path=/; SameSite=Lax; Max-Age=0" +
                    secure;
            }

            result.token = readCookie(name);

            if (
                args.operation === "set" &&
                result.token !== args.token
            ) {
                result.error =
                    "The browser did not save the persistent login cookie.";
            }

            if (
                args.operation === "delete" &&
                result.token
            ) {
                result.error =
                    "The browser did not remove the login cookie.";
            }
        } catch (error) {
            result.error = String(error);
        }

        send("streamlit:setComponentValue", {
            value: result,
            dataType: "json"
        });

        send("streamlit:setFrameHeight", {height: 0});
    });

    send("streamlit:componentReady", {apiVersion: 1});
    send("streamlit:setFrameHeight", {height: 0});
})();
</script>
</body>
</html>
"""


HELPERS = r'''
# PERSISTENT_LOGIN_DATABASE_TOKEN_V1
def _persistent_login_initialize():
    conn = get_db_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_login_tokens (
                token_hash TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                password_version TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _persistent_login_digest(value):
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _persistent_login_component():
    from pathlib import Path
    import streamlit.components.v1 as components

    return components.declare_component(
        "horse_checklist_persistent_login_v1",
        path=str(
            Path(__file__).resolve().parent
            / "_persistent_login_component"
        ),
    )


def _persistent_login_cookie_name():
    # Different local application directories get different cookie names.
    from pathlib import Path

    application_id = _persistent_login_digest(
        str(Path(__file__).resolve())
    )[:12]

    return f"horse_checklist_login_{application_id}"


def _persistent_login_revoke(token):
    if not token:
        return

    conn = get_db_connection()

    try:
        conn.execute(
            """
            DELETE FROM persistent_login_tokens
            WHERE token_hash = ?
            """,
            (_persistent_login_digest(token),),
        )
        conn.commit()
    finally:
        conn.close()


def _persistent_login_lookup(token):
    if not isinstance(token, str) or not 40 <= len(token) <= 128:
        return None

    conn = get_db_connection()

    try:
        row = conn.execute(
            """
            SELECT
                users.id,
                users.display_name,
                users.password,
                persistent_login_tokens.password_version
            FROM persistent_login_tokens
            JOIN users
                ON users.id = persistent_login_tokens.owner_id
            WHERE persistent_login_tokens.token_hash = ?
            """,
            (_persistent_login_digest(token),),
        ).fetchone()

        if row is None:
            return None

        if (
            _persistent_login_digest(row["password"])
            != row["password_version"]
        ):
            conn.execute(
                """
                DELETE FROM persistent_login_tokens
                WHERE token_hash = ?
                """,
                (_persistent_login_digest(token),),
            )
            conn.commit()
            return None

        return {
            "id": row["id"],
            "display_name": row["display_name"],
        }
    finally:
        conn.close()


def _persistent_login_issue(owner_id):
    import secrets

    _persistent_login_initialize()

    old_token = st.session_state.get("_persistent_login_token")
    _persistent_login_revoke(old_token)

    token = secrets.token_urlsafe(48)
    conn = get_db_connection()

    try:
        user = conn.execute(
            "SELECT password FROM users WHERE id = ?",
            (owner_id,),
        ).fetchone()

        if user is None:
            raise ValueError("The user account no longer exists.")

        conn.execute(
            """
            INSERT INTO persistent_login_tokens (
                token_hash,
                owner_id,
                password_version
            )
            VALUES (?, ?, ?)
            """,
            (
                _persistent_login_digest(token),
                owner_id,
                _persistent_login_digest(user["password"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    st.session_state["_persistent_login_token"] = token
    st.session_state["_persistent_login_pending"] = {
        "operation": "set",
        "token": token,
        "request_id": secrets.token_hex(16),
    }


def _persistent_login_logout():
    import secrets

    _persistent_login_revoke(
        st.session_state.get("_persistent_login_token")
    )

    st.session_state.clear()

    st.session_state["_persistent_login_pending"] = {
        "operation": "delete",
        "token": "",
        "request_id": secrets.token_hex(16),
    }


def _persistent_login_bootstrap():
    import secrets

    _persistent_login_initialize()

    if "_persistent_login_read_request" not in st.session_state:
        st.session_state["_persistent_login_read_request"] = (
            secrets.token_hex(16)
        )

    pending = st.session_state.get("_persistent_login_pending")

    request = pending or {
        "operation": "read",
        "token": "",
        "request_id": st.session_state[
            "_persistent_login_read_request"
        ],
    }

    component = _persistent_login_component()

    result = component(
        cookie_name=_persistent_login_cookie_name(),
        operation=request["operation"],
        token=request["token"],
        request_id=request["request_id"],
        key="_persistent_login_cookie_bridge",
        default=None,
    )

    # Wait for the browser's acknowledgement rather than restoring login
    # from a stale component return value.
    if (
        not isinstance(result, dict)
        or result.get("request_id") != request["request_id"]
    ):
        st.info("Restoring login session…")
        st.stop()

    if result.get("error"):
        st.warning(
            "Persistent login storage is unavailable in this browser. "
            "Your current login can still be used, but another login "
            "may be required after a reload."
        )

    if pending:
        st.session_state.pop("_persistent_login_pending", None)

        if pending["operation"] == "delete":
            st.session_state["logged_in"] = False
            st.session_state.pop("_persistent_login_token", None)
            return

        # A successfully authenticated user can keep using the current
        # session even if the browser refuses persistent cookie storage.
        token = pending["token"]
    else:
        token = (
            st.session_state.get("_persistent_login_token")
            or result.get("token", "")
        )

    user = _persistent_login_lookup(token)

    if user is None:
        st.session_state["logged_in"] = False
        st.session_state.pop("user_id", None)
        st.session_state.pop("display_name", None)
        st.session_state.pop("_persistent_login_token", None)
        return

    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user["id"]
    st.session_state["display_name"] = user["display_name"]
    st.session_state["_persistent_login_token"] = token

'''


def find_function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {name} function; found {len(matches)}."
        )

    return matches[0]


def is_session_user_assignment(node):
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
        and isinstance(node.targets[0].value, ast.Attribute)
        and isinstance(node.targets[0].value.value, ast.Name)
        and node.targets[0].value.value.id == "st"
        and node.targets[0].value.attr == "session_state"
        and node.targets[0].attr == "user_id"
        and isinstance(node.value, ast.Name)
        and node.value.id == "user_id"
    )


def is_logout_condition(node):
    if not isinstance(node, ast.If):
        return False

    call = node.test

    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "button"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "sidebar"
        and isinstance(call.func.value.value, ast.Name)
        and call.func.value.value.id == "st"
        and bool(call.args)
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "Logout"
    )


class PatchLogin(ast.NodeTransformer):
    def __init__(self):
        self.count = 0

    def visit_Assign(self, node):
        if is_session_user_assignment(node):
            self.count += 1
            return [
                node,
                ast.parse(
                    "_persistent_login_issue(user_id)"
                ).body[0],
            ]

        return node


class PatchMain(ast.NodeTransformer):
    def __init__(self):
        self.logout_count = 0

    def visit_If(self, node):
        if is_logout_condition(node):
            self.logout_count += 1
            node.body = ast.parse(
                "_persistent_login_logout()\nst.rerun()"
            ).body
            return node

        return self.generic_visit(node)


def patch_application(source):
    if PATCH_MARKER in source:
        return source

    tree = ast.parse(source)

    find_function(tree, "get_db_connection")
    login = find_function(tree, "render_login_page")
    main = find_function(tree, "main")

    if login.decorator_list or main.decorator_list:
        raise ValueError("Unexpected login or main decorators.")

    login_start, login_end = login.lineno - 1, login.end_lineno
    main_start, main_end = main.lineno - 1, main.end_lineno

    login_transformer = PatchLogin()
    updated_login = login_transformer.visit(login)

    if login_transformer.count != 1:
        raise ValueError(
            "Could not uniquely identify the successful login assignment."
        )

    main_transformer = PatchMain()
    updated_main = main_transformer.visit(main)

    if main_transformer.logout_count != 1:
        raise ValueError("Could not uniquely identify the Logout button.")

    initialization_positions = [
        index
        for index, statement in enumerate(updated_main.body)
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "init_db"
        )
    ]

    if len(initialization_positions) != 1:
        raise ValueError(
            "Could not uniquely identify init_db() inside main()."
        )

    updated_main.body.insert(
        initialization_positions[0] + 1,
        ast.parse("_persistent_login_bootstrap()").body[0],
    )

    ast.fix_missing_locations(updated_login)
    ast.fix_missing_locations(updated_main)

    edits = [
        (
            login_start,
            login_end,
            HELPERS.strip("\n")
            + "\n\n"
            + ast.unparse(updated_login)
            + "\n\n",
        ),
        (
            main_start,
            main_end,
            ast.unparse(updated_main) + "\n\n",
        ),
    ]

    lines = source.splitlines(keepends=True)

    for start, end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        lines[start:end] = [replacement]

    updated = "".join(lines)
    compile(updated, "<persistent-login-patch>", "exec")

    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Add revocable, cookie-backed persistent login."
    )
    parser.add_argument("app_file", nargs="?", default="app.py")
    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")
    component_directory = app_path.parent / "_persistent_login_component"
    component_path = component_directory / "index.html"

    if PATCH_MARKER in source:
        if not component_path.is_file():
            raise SystemExit(
                "The app is patched, but its cookie component is missing. "
                "Restore _persistent_login_component/index.html from "
                "the original deployment."
            )
        print("Persistent login is already installed.")
        return

    try:
        updated = patch_application(source)
    except Exception as error:
        raise SystemExit(
            f"Validation failed. Application was not changed.\n{error}"
        ) from error

    backup = app_path.with_name(
        f"{app_path.name}.before-persistent-login.bak"
    )

    if backup.exists():
        raise SystemExit(f"Backup already exists: {backup}")

    if component_path.exists():
        raise SystemExit(
            f"Component file already exists: {component_path}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(app_path, backup)
    component_directory.mkdir(parents=True, exist_ok=True)
    component_path.write_text(COMPONENT_HTML, encoding="utf-8")

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
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
    print(f"Backup: {backup}")
    print(f"Required component directory: {component_directory}")
    print("Deploy the component directory alongside the application.")
    print("Python syntax validation passed.")
    print("Restart or redeploy, then log in once to create a login cookie.")
    print("Logout revokes the current browser token.")
    print("Browser reload and physical-device testing are still required.")
    print("Use HTTPS and persistent database storage in production.")


if __name__ == "__main__":
    main()
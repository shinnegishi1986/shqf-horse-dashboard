# scripts/edit-race-template.py
#
# Adds editing and deletion to the Race Templates page.
#
# Requires:
#   - Corrected race-feature updater (20261114 V2)
#   - Race-template venue patch
#
# Compatible with the article-editing and Memo-table patches.
#
# Safety:
#   - Source backup before replacement
#   - Syntax and AST change-scope validation
#   - No database migration
#   - No database writes while applying this script
#   - Edits preserve template IDs and blog associations
#   - Duplicate template conflicts do not overwrite another template
#   - Linked blog articles block template deletion
#   - Existing checklist records are not changed
#
# Stop Streamlit before running.
#
# Run:
#   python scripts/edit-race-template.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# RACE_TEMPLATE_EDIT_DELETE_V1"


RUNTIME = r'''
# RACE_TEMPLATE_EDIT_DELETE_V1

def _rt_fields():
    return (
        "race_name_id",
        "race_date",
        "program_number",
        "distance",
        "number_of_horses",
        "race_class_id",
        "venue_id",
    )


def _rt_current(conn, owner_id, template_id, expected):
    found = conn.execute(
        "SELECT * FROM rf_race_templates "
        "WHERE owner_id=? AND id=?",
        (owner_id, template_id),
    ).fetchone()

    if found is None:
        raise ValueError("This template is unavailable.")

    current = dict(found)

    if any(
        current.get(key) != expected.get(key)
        for key in _rt_fields()
    ):
        raise ValueError(
            "This template changed after the editor was opened. "
            "Your changes were not saved. "
            "Reload the stored template first."
        )

    return current


def _rt_update(
    owner_id,
    template_id,
    expected,
    race_name_id,
    new_name,
    race_date,
    program,
    distance,
    horses,
    class_id,
    venue_id,
):
    if venue_id is None:
        raise ValueError("Select a venue.")

    if not date(1980, 1, 1) <= race_date <= date(2100, 12, 31):
        raise ValueError(
            "Race date must be between 1980 and 2100."
        )

    if not (
        1 <= int(program) <= 12
        and 1 <= int(distance) <= 5000
        and 1 <= int(horses) <= 18
    ):
        raise ValueError(
            "Program, distance, or number of horses "
            "is outside the supported range."
        )

    conn = _rf_db()

    try:
        conn.execute("BEGIN IMMEDIATE")

        try:
            _rt_current(
                conn,
                owner_id,
                template_id,
                expected,
            )

            if not conn.execute(
                "SELECT 1 FROM venues "
                "WHERE owner_id=? AND id=?",
                (owner_id, venue_id),
            ).fetchone():
                raise ValueError(
                    "The selected venue is unavailable "
                    "for this account."
                )

            if class_id is not None and not conn.execute(
                "SELECT 1 FROM race_classes "
                "WHERE owner_id=? AND id=?",
                (owner_id, class_id),
            ).fetchone():
                raise ValueError(
                    "The selected race class is unavailable "
                    "for this account."
                )

            if race_name_id is None:
                name = str(new_name or "").strip()

                if not name or len(name) > 200:
                    raise ValueError(
                        "Enter a new race name of 1–200 characters."
                    )

                existing = conn.execute(
                    "SELECT id FROM race_names "
                    "WHERE owner_id=? "
                    "AND RF_CASEFOLD(race_name)=RF_CASEFOLD(?)",
                    (owner_id, name),
                ).fetchone()

                if existing:
                    race_name_id = existing["id"]

                else:
                    race_name_id = conn.execute(
                        "INSERT INTO race_names(owner_id,race_name) "
                        "VALUES (?,?)",
                        (owner_id, name),
                    ).lastrowid

            elif not conn.execute(
                "SELECT 1 FROM race_names "
                "WHERE owner_id=? AND id=?",
                (owner_id, race_name_id),
            ).fetchone():
                raise ValueError(
                    "The selected race name is unavailable "
                    "for this account."
                )

            conn.execute("""
                UPDATE rf_race_templates
                SET race_name_id=?,
                    race_date=?,
                    program_number=?,
                    distance=?,
                    number_of_horses=?,
                    race_class_id=?,
                    venue_id=?
                WHERE owner_id=? AND id=?
            """, (
                race_name_id,
                race_date.isoformat(),
                int(program),
                int(distance),
                int(horses),
                class_id,
                venue_id,
                owner_id,
                template_id,
            ))

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    finally:
        conn.close()


def _rt_delete(owner_id, template_id, expected):
    conn = _rf_db()

    try:
        conn.execute("BEGIN IMMEDIATE")

        try:
            _rt_current(
                conn,
                owner_id,
                template_id,
                expected,
            )

            if conn.execute(
                "SELECT 1 FROM rf_blog_posts "
                "WHERE template_id=? LIMIT 1",
                (template_id,),
            ).fetchone():
                raise ValueError(
                    "This template is linked to a blog article "
                    "and cannot be deleted. Edit the linked articles "
                    "and select another template first."
                )

            cursor = conn.execute(
                "DELETE FROM rf_race_templates "
                "WHERE owner_id=? AND id=?",
                (owner_id, template_id),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "This template is unavailable."
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    finally:
        conn.close()


def _rt_reload(owner_id, template_id):
    st.session_state.pop(
        f"rt_snapshot_{owner_id}_{template_id}",
        None,
    )

    key = f"rt_generation_{owner_id}_{template_id}"

    st.session_state[key] = (
        st.session_state.get(key, 0) + 1
    )


def _rt_manage(owner_id):
    st.markdown("---")
    st.subheader("Edit or Delete Race Templates")

    notice = st.session_state.pop(
        f"rt_notice_{owner_id}",
        None,
    )

    if notice:
        st.success(notice)

    rows = _rf_templates(owner_id)

    if not rows:
        st.info("No race templates are registered.")
        return

    lookup = {
        row["id"]: row
        for row in rows
    }

    selected = st.selectbox(
        "Template to edit or delete",
        list(lookup),
        format_func=lambda value: (
            f"#{value} | {_rf_label(lookup[value])}"
        ),
        key=f"rt_selected_{owner_id}",
    )

    current = lookup[selected]
    snapshot_key = f"rt_snapshot_{owner_id}_{selected}"

    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = dict(current)

    saved = st.session_state[snapshot_key]

    st.button(
        "Reload Stored Template",
        key=f"rt_reload_{owner_id}_{selected}",
        on_click=_rt_reload,
        args=(owner_id, selected),
        help=(
            "Discard the editor's unsaved fields "
            "and load the current template."
        ),
    )

    if any(
        current.get(key) != saved.get(key)
        for key in _rt_fields()
    ):
        st.warning(
            "The stored template changed. "
            "Reload it before saving or deleting."
        )

    generation = st.session_state.get(
        f"rt_generation_{owner_id}_{selected}",
        0,
    )

    prefix = (
        f"rt_edit_{owner_id}_{selected}_{generation}"
    )

    names = {
        row["id"]: row["race_name"]
        for row in get_user_race_names(owner_id)
    }

    venues = {
        row["id"]: row["venue_name"]
        for row in get_user_venues(owner_id)
    }

    class_ids, class_labels = _rf_class_options(owner_id)
    classes = dict(zip(class_ids, class_labels))

    name_ids = [None] + list(names)
    venue_ids = [None] + list(venues)

    initial_name = (
        saved.get("race_name_id")
        if saved.get("race_name_id") in names
        else None
    )

    initial_venue = (
        saved.get("venue_id")
        if saved.get("venue_id") in venues
        else None
    )

    initial_class = (
        saved.get("race_class_id")
        if saved.get("race_class_id") in classes
        else None
    )

    try:
        initial_date = date.fromisoformat(
            saved["race_date"]
        )

    except (ValueError, TypeError):
        initial_date = date.today()

        st.warning(
            "The stored date is invalid. "
            "Choose the correct date before saving."
        )

    initial_date = max(
        date(1980, 1, 1),
        min(date(2100, 12, 31), initial_date),
    )

    st.caption(
        "Edits preserve the template ID and its blog links. "
        "Existing checklist records are not changed. "
        "Choosing a different race name does not rename "
        "the shared Race Names entry."
    )

    with st.form(prefix):
        name_id = st.selectbox(
            "Race name",
            name_ids,
            index=name_ids.index(initial_name),
            format_func=lambda value: (
                "(Use a new race name)"
                if value is None
                else names[value]
            ),
            key=prefix + "_name",
        )

        new_name = st.text_input(
            "New race name — only used when "
            "Use a new race name is selected",
            max_chars=200,
            key=prefix + "_new_name",
        )

        venue_id = st.selectbox(
            "Venue",
            venue_ids,
            index=venue_ids.index(initial_venue),
            format_func=lambda value: (
                "(Select a venue)"
                if value is None
                else venues[value]
            ),
            key=prefix + "_venue",
        )

        race_date = st.date_input(
            "Race date",
            value=initial_date,
            min_value=date(1980, 1, 1),
            max_value=date(2100, 12, 31),
            key=prefix + "_date",
        )

        program = st.number_input(
            "Program number",
            min_value=1,
            max_value=12,
            value=max(
                1,
                min(
                    12,
                    int(saved.get("program_number") or 1),
                ),
            ),
            key=prefix + "_program",
        )

        distance = st.number_input(
            "Distance (meters)",
            min_value=1,
            max_value=5000,
            value=max(
                1,
                min(
                    5000,
                    int(saved.get("distance") or 1600),
                ),
            ),
            step=100,
            key=prefix + "_distance",
        )

        horses = st.number_input(
            "Number of horses",
            min_value=1,
            max_value=18,
            value=max(
                1,
                min(
                    18,
                    int(saved.get("number_of_horses") or 18),
                ),
            ),
            key=prefix + "_horses",
        )

        class_id = st.selectbox(
            "Race class",
            class_ids,
            index=class_ids.index(initial_class),
            format_func=lambda value: classes[value],
            key=prefix + "_class",
        )

        submit = st.form_submit_button(
            "Save Template Changes"
        )

    if submit:
        try:
            _rt_update(
                owner_id,
                selected,
                saved,
                name_id,
                new_name,
                race_date,
                program,
                distance,
                horses,
                class_id,
                venue_id,
            )

        except sqlite3.IntegrityError:
            st.error(
                "Changes were not saved. Another template may "
                "already use that race name, date, and program "
                "number, or a referenced item is unavailable. "
                "No other template was overwritten."
            )

        except (ValueError, sqlite3.Error) as error:
            st.error(
                f"Changes were not saved: {error}"
            )

        else:
            _rt_reload(owner_id, selected)

            st.session_state[
                f"rt_notice_{owner_id}"
            ] = f"Template #{selected} updated."

            st.rerun()

    with st.expander(
        "Delete Selected Template",
        expanded=False,
    ):
        linked = _rf_rows(
            "SELECT COUNT(*) AS n FROM rf_blog_posts "
            "WHERE template_id=?",
            (selected,),
        )[0]["n"]

        if linked:
            st.warning(
                f"This template has {linked} linked blog article(s). "
                "Move those articles to another template "
                "before deleting it."
            )

        st.caption(
            "Deletion removes only this saved template. "
            "It does not delete checklists, race names, venues, "
            "classes, articles, tags, or images."
        )

        confirmed = st.checkbox(
            f"Permanently delete template #{selected}",
            key=prefix + "_confirm_delete",
        )

        if st.button(
            "Delete Template Permanently",
            key=prefix + "_delete",
            disabled=not confirmed or bool(linked),
        ):
            try:
                _rt_delete(
                    owner_id,
                    selected,
                    saved,
                )

            except (ValueError, sqlite3.Error) as error:
                st.error(
                    f"Template was not deleted: {error}"
                )

            else:
                _rt_reload(owner_id, selected)

                st.session_state[
                    f"rt_notice_{owner_id}"
                ] = f"Template #{selected} deleted."

                st.rerun()

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


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    required = {
        "_rf_templates_page",
        "_rf_templates",
        "_rf_label",
        "_rf_db",
        "_rf_rows",
        "_rf_class_options",
        "_rf_venue_migrate",
        "get_user_race_names",
        "get_user_venues",
    }

    functions = {
        name: find_function(tree, name)
        for name in required
    }

    page = functions["_rf_templates_page"]

    if not any(
        argument.arg == "owner_id"
        for argument in page.args.args
    ):
        raise ValueError(
            "Unexpected Race Templates page signature."
        )

    runtime_tree = ast.parse(RUNTIME)

    helper_names = {
        node.name
        for node in runtime_tree.body
        if isinstance(node, ast.FunctionDef)
    }

    existing_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    conflicts = helper_names.intersection(existing_names)

    if conflicts:
        raise ValueError(
            "Conflicting template-manager helpers exist: "
            + ", ".join(sorted(conflicts))
        )

    start = definition_start(page)
    end = page.end_lineno

    page.body.extend(
        ast.parse("_rt_manage(owner_id)").body
    )

    ast.fix_missing_locations(page)

    lines = source.splitlines(keepends=True)

    lines[start:end] = [
        ast.unparse(page) + "\n\n"
    ]

    intermediate = "".join(lines)
    intermediate_tree = ast.parse(intermediate)

    first_definition = next(
        (
            node
            for node in intermediate_tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.ClassDef),
            )
        ),
        None,
    )

    if first_definition is None:
        raise ValueError(
            "Cannot find a safe helper insertion point."
        )

    lines = intermediate.splitlines(keepends=True)

    lines.insert(
        definition_start(first_definition),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<race-template-edit-delete>",
        "exec",
    )

    permitted = helper_names | {
        "_rf_templates_page"
    }

    def normalize(text):
        parsed = ast.parse(text)

        parsed.body = [
            node
            for node in parsed.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in permitted
            )
        ]

        return ast.dump(
            parsed,
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside "
            "Race Templates integration points."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid template-manager patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add edit and delete controls "
            "to the Race Templates page."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    arguments = parser.parse_args()
    app_path = Path(arguments.app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    original_bytes = app_path.read_bytes()

    try:
        source = original_bytes.decode("utf-8-sig")
        updated, changed = patch_application(source)

    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}\n"
            "This patch requires the earlier race-feature "
            "and race-template venue updates."
        ) from error

    if not changed:
        print(
            "Race-template edit/delete controls "
            "are already installed. No changes were made."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup_path = app_path.with_name(
        f"{app_path.name}.before-template-edit-{timestamp}.bak"
    )

    temporary_path = None

    try:
        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed during validation. "
                "Run the patch again."
            )

        shutil.copy2(app_path, backup_path)

        if backup_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app_path.parent,
            prefix=f".{app_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            temporary_file.write(updated)

        shutil.copymode(
            app_path,
            temporary_path,
        )

        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed before replacement. "
                "Run the patch again."
            )

        temporary_path.replace(app_path)
        temporary_path = None

    except Exception as error:
        raise SystemExit(
            "Patch could not be completed.\n"
            f"{error}"
        ) from error

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Source backup: {backup_path}")
    print("Python syntax and AST-scope validation passed.")
    print("No database records or schema were changed by this script.")
    print("Restart Streamlit, then open Race Templates.")
    print("Use Edit or Delete Race Templates below the existing form.")
    print("Saving preserves template IDs and blog associations.")
    print("Templates linked to blog articles cannot be deleted.")
    print("Existing checklist records are not updated or deleted.")
    print("Interactive browser testing remains required.")


if __name__ == "__main__":
    main()
# scripts/implement-blog-feature.py
#
# Adds:
#   - Editing existing race-blog articles.
#   - Enter-key tag entry instead of comma-separated entry.
#   - Editing title, text, race template, tags, and images.
#   - Explicit image removal; existing images are otherwise preserved.
#   - Revision checks to prevent silently overwriting concurrent edits.
#
# Requires the corrected race-feature updater (20261114 V2).
# Compatible with the subsequent race-template venue patch.
#
# Stop Streamlit before running.
#
# Run:
#   python scripts/implement-blog-feature.py app.py
#
# Optional explicit database:
#   python scripts/implement-blog-feature.py app.py \
#       --database data/horse_checklist_app.db
#
# Creates source/database backups.
# Database migration runs on the next application startup.
#
# Existing articles, tags, template associations, and image BLOBs
# are not removed by the migration.

import argparse
import ast
from pathlib import Path
import shutil
import sqlite3
import tempfile


MARKER = "# RACE_BLOG_EDIT_AND_ENTER_TAGS_V1"


RUNTIME = r'''
# RACE_BLOG_EDIT_AND_ENTER_TAGS_V1

def _rb_migrate():
    conn = _rf_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(rf_blog_posts)"
                )
            }

            if not columns:
                raise RuntimeError(
                    "Race-blog tables are missing. "
                    "Install the race-feature update first."
                )

            if "revision" not in columns:
                conn.execute(
                    "ALTER TABLE rf_blog_posts "
                    "ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )

            if "updated_at" not in columns:
                conn.execute(
                    "ALTER TABLE rf_blog_posts "
                    "ADD COLUMN updated_at TEXT"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    finally:
        conn.close()


def _rb_tags(values):
    # Strings are treated as newline-separated, never comma-separated.
    if isinstance(values, str):
        values = values.splitlines()

    result = {}

    for value in values or []:
        tag = str(value).strip()

        if not tag:
            continue

        if "\n" in tag or "\r" in tag:
            raise ValueError("Each tag must occupy a single line.")

        if len(tag) > 60:
            raise ValueError(
                "Each tag must be 60 characters or fewer."
            )

        result.setdefault(tag.casefold(), tag)

    if len(result) > 20:
        raise ValueError("Use no more than 20 tags.")

    return result


def _rb_tag_options(owner_id):
    rows = _rf_rows("""
        SELECT DISTINCT t.name, t.normalized
        FROM rf_blog_tags t
        JOIN rf_blog_post_tags pt ON pt.tag_id = t.id
        JOIN rf_blog_posts p ON p.id = pt.post_id
        WHERE t.owner_id = ? AND p.owner_id = ?
        ORDER BY t.normalized
    """, (owner_id, owner_id))

    return [row["name"] for row in rows]


def _rb_tag_input(owner_id, label, key, initial=None):
    import inspect

    initial = list(_rb_tags(initial or []).values())
    options = {}

    for value in _rb_tag_options(owner_id) + initial:
        options.setdefault(value.casefold(), value)

    # Keep the initial spelling in the available/default selections.
    for value in initial:
        options[value.casefold()] = value

    available = list(options.values())

    try:
        parameters = inspect.signature(
            st.multiselect
        ).parameters
    except (TypeError, ValueError):
        parameters = {}

    if "accept_new_options" in parameters:
        kwargs = {
            "label": label,
            "options": available,
            "default": initial,
            "key": key,
            "accept_new_options": True,
            "max_selections": 20,
            "help": (
                "Type a tag and press Enter to add it. "
                "Use the x on a tag to remove it. "
                "Commas are not separators."
            ),
        }

        # Avoid Enter accidentally selecting all matching options
        # on versions that provide this setting.
        if "select_all" in parameters:
            kwargs["select_all"] = False

        return st.multiselect(**kwargs)

    text = st.text_area(
        label + " — one tag per line",
        value="\n".join(initial),
        key=key,
        height=100,
        help=(
            "Press Enter after each tag. "
            "Each nonempty line becomes one tag. "
            "Commas are not separators."
        ),
    )

    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]


def _rb_post_tags(owner_id, post_id):
    rows = _rf_rows("""
        SELECT t.name
        FROM rf_blog_post_tags pt
        JOIN rf_blog_tags t ON t.id = pt.tag_id
        JOIN rf_blog_posts p ON p.id = pt.post_id
        WHERE p.owner_id = ?
          AND p.id = ?
          AND t.owner_id = ?
        ORDER BY t.normalized
    """, (owner_id, post_id, owner_id))

    return [row["name"] for row in rows]


def _rb_image_metadata(owner_id, post_id):
    return _rf_rows("""
        SELECT id, filename, mime_type,
               length(image_data) AS byte_count
        FROM rf_blog_images
        WHERE owner_id = ? AND post_id = ?
        ORDER BY id
    """, (owner_id, post_id))


def _rb_save(
    owner_id,
    template_id,
    title,
    body,
    tag_values,
    uploads,
    post_id=None,
    expected_revision=None,
    remove_image_ids=None,
):
    title = str(title or "").strip()
    body = str(body or "").strip()

    if not title or len(title) > 200:
        raise ValueError(
            "Enter an article title of 1–200 characters."
        )

    if not body or len(body) > 200_000:
        raise ValueError(
            "Enter article text of 1–200,000 characters."
        )

    tags = _rb_tags(tag_values)
    removals = set(remove_image_ids or [])

    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in removals
    ):
        raise ValueError("Invalid image selection.")

    if post_id is not None:
        existing = _rf_rows(
            "SELECT id FROM rf_blog_posts "
            "WHERE owner_id = ? AND id = ?",
            (owner_id, post_id),
        )

        if not existing:
            raise ValueError(
                "The article is unavailable for this account."
            )

        if expected_revision is None:
            raise ValueError(
                "The article revision is missing. Reload the article."
            )

    elif removals:
        raise ValueError(
            "Images cannot be removed from an unsaved article."
        )

    # Reuse the existing image validation/normalization.
    prepared_images = _rf_images(list(uploads or []))

    # Validates ownership of the associated template.
    _rf_template(owner_id, template_id)

    conn = _rf_db()

    try:
        with conn:
            if not conn.execute(
                "SELECT 1 FROM rf_race_templates "
                "WHERE owner_id = ? AND id = ?",
                (owner_id, template_id),
            ).fetchone():
                raise ValueError(
                    "The selected race template is unavailable."
                )

            if post_id is None:
                cursor = conn.execute("""
                    INSERT INTO rf_blog_posts(
                        owner_id, template_id, title, body,
                        revision, updated_at
                    )
                    VALUES (?, ?, ?, ?, 0, NULL)
                """, (
                    owner_id,
                    template_id,
                    title,
                    body,
                ))

                saved_id = cursor.lastrowid
                old_images = []

            else:
                cursor = conn.execute("""
                    UPDATE rf_blog_posts
                    SET template_id = ?,
                        title = ?,
                        body = ?,
                        updated_at = CURRENT_TIMESTAMP,
                        revision = revision + 1
                    WHERE owner_id = ?
                      AND id = ?
                      AND revision = ?
                """, (
                    template_id,
                    title,
                    body,
                    owner_id,
                    post_id,
                    int(expected_revision),
                ))

                if cursor.rowcount != 1:
                    raise ValueError(
                        "This article changed after you opened the editor. "
                        "Your changes were not saved. Copy any text you "
                        "want to keep, then click Reload Stored Article."
                    )

                saved_id = post_id

                old_images = [
                    dict(row)
                    for row in conn.execute("""
                        SELECT id, length(image_data) AS byte_count
                        FROM rf_blog_images
                        WHERE owner_id = ? AND post_id = ?
                    """, (owner_id, saved_id))
                ]

            valid_image_ids = {
                row["id"] for row in old_images
            }

            if not removals.issubset(valid_image_ids):
                raise ValueError(
                    "An image selected for removal is unavailable."
                )

            retained_images = [
                row
                for row in old_images
                if row["id"] not in removals
            ]

            if len(retained_images) + len(prepared_images) > 6:
                raise ValueError(
                    "An article can contain at most six images. "
                    "Select existing images for removal before "
                    "adding more."
                )

            retained_bytes = sum(
                row["byte_count"] or 0
                for row in retained_images
            )

            new_bytes = sum(
                len(data)
                for _, _, data in prepared_images
            )

            if retained_bytes + new_bytes > 20 * 1024 * 1024:
                raise ValueError(
                    "Combined stored images for this article "
                    "must not exceed 20 MB."
                )

            # Replace only this article's tag associations.
            conn.execute(
                "DELETE FROM rf_blog_post_tags WHERE post_id = ?",
                (saved_id,),
            )

            for normalized, name in tags.items():
                conn.execute("""
                    INSERT INTO rf_blog_tags(
                        owner_id, name, normalized
                    )
                    VALUES (?, ?, ?)
                    ON CONFLICT(owner_id, normalized) DO NOTHING
                """, (owner_id, name, normalized))

                tag_id = conn.execute(
                    "SELECT id FROM rf_blog_tags "
                    "WHERE owner_id = ? AND normalized = ?",
                    (owner_id, normalized),
                ).fetchone()["id"]

                conn.execute(
                    "INSERT INTO rf_blog_post_tags(post_id, tag_id) "
                    "VALUES (?, ?)",
                    (saved_id, tag_id),
                )

            for image_id in removals:
                conn.execute(
                    "DELETE FROM rf_blog_images "
                    "WHERE owner_id = ? AND post_id = ? AND id = ?",
                    (owner_id, saved_id, image_id),
                )

            for filename, mime, data in prepared_images:
                conn.execute("""
                    INSERT INTO rf_blog_images(
                        owner_id, post_id, filename,
                        mime_type, image_data
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    owner_id,
                    saved_id,
                    filename,
                    mime,
                    sqlite3.Binary(data),
                ))

        return saved_id

    finally:
        conn.close()


def _rb_search(owner_id, query, tag_values, page=1):
    required_tags = _rb_tags(tag_values)
    clauses = ["p.owner_id = ?"]
    parameters = [owner_id]
    query = str(query or "").strip()

    if query:
        clauses.append("""
            (
                instr(
                    RF_CASEFOLD(p.title || ' ' || p.body),
                    RF_CASEFOLD(?)
                ) > 0
                OR EXISTS (
                    SELECT 1
                    FROM rf_blog_post_tags pt
                    JOIN rf_blog_tags t ON t.id = pt.tag_id
                    WHERE pt.post_id = p.id
                      AND t.owner_id = p.owner_id
                      AND instr(t.normalized, RF_CASEFOLD(?)) > 0
                )
            )
        """)

        parameters.extend([query, query])

    for normalized in required_tags:
        clauses.append("""
            EXISTS (
                SELECT 1
                FROM rf_blog_post_tags pt
                JOIN rf_blog_tags t ON t.id = pt.tag_id
                WHERE pt.post_id = p.id
                  AND t.owner_id = p.owner_id
                  AND t.normalized = ?
            )
        """)

        parameters.append(normalized)

    where = " AND ".join(clauses)

    count = _rf_rows(
        "SELECT COUNT(*) AS n FROM rf_blog_posts p WHERE " + where,
        parameters,
    )[0]["n"]

    rows = _rf_rows(
        "SELECT p.id, p.title, p.created_at, p.updated_at "
        "FROM rf_blog_posts p WHERE "
        + where
        + " ORDER BY p.id DESC LIMIT 20 OFFSET ?",
        parameters + [max(0, int(page) - 1) * 20],
    )

    return count, rows


def _rb_reload_editor(owner_id, post_id):
    st.session_state.pop(
        f"rb_edit_snapshot_{owner_id}_{post_id}",
        None,
    )

    generation_key = f"rb_edit_generation_{owner_id}_{post_id}"

    st.session_state[generation_key] = (
        st.session_state.get(generation_key, 0) + 1
    )


def _rb_edit_article(owner_id, post, templates):
    post_id = post["id"]
    snapshot_key = f"rb_edit_snapshot_{owner_id}_{post_id}"

    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = {
            "revision": int(post["revision"]),
            "title": post["title"],
            "body": post["body"],
            "template_id": post["template_id"],
            "tags": _rb_post_tags(owner_id, post_id),
        }

    snapshot = st.session_state[snapshot_key]

    st.button(
        "Reload Stored Article",
        key=f"rb_reload_article_{owner_id}_{post_id}",
        on_click=_rb_reload_editor,
        args=(owner_id, post_id),
        help=(
            "Discard this editor's unsaved fields and reload "
            "the stored article on the next render."
        ),
    )

    if int(post["revision"]) != snapshot["revision"]:
        st.warning(
            "The stored article has changed since this editor "
            "was opened. Copy any unsaved text you want to retain, "
            "then reload before saving."
        )

    if not templates:
        st.info(
            "A race template is required to save an article."
        )
        return

    template_ids = list(templates)
    initial_template = snapshot["template_id"]

    if initial_template not in templates:
        initial_template = template_ids[0]
        st.warning(
            "The original race template is unavailable. "
            "Choose a replacement before saving."
        )

    generation = st.session_state.get(
        f"rb_edit_generation_{owner_id}_{post_id}",
        0,
    )

    prefix = (
        f"rb_edit_{owner_id}_{post_id}_"
        f"{snapshot['revision']}_{generation}"
    )

    image_rows = _rb_image_metadata(owner_id, post_id)
    image_lookup = {
        row["id"]: row for row in image_rows
    }

    with st.form(prefix):
        template_id = st.selectbox(
            "Race template",
            template_ids,
            index=template_ids.index(initial_template),
            format_func=lambda value: _rf_label(templates[value]),
            key=prefix + "_template",
        )

        title = st.text_input(
            "Article title",
            value=snapshot["title"],
            max_chars=200,
            key=prefix + "_title",
        )

        body = st.text_area(
            "Article text — Markdown supported",
            value=snapshot["body"],
            max_chars=200_000,
            height=320,
            key=prefix + "_body",
        )

        tags = _rb_tag_input(
            owner_id,
            "Tags — type a tag and press Enter",
            prefix + "_tags",
            snapshot["tags"],
        )

        removals = st.multiselect(
            "Existing images to remove — leave empty to keep all",
            list(image_lookup),
            format_func=lambda value: (
                f"#{value} — {image_lookup[value]['filename']}"
            ),
            key=prefix + "_remove_images",
        )

        uploads = st.file_uploader(
            "Add images — existing images are kept unless selected above",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key=prefix + "_uploads",
        )

        st.caption(
            "Maximum six stored images per article, 20 MB combined. "
            "New image uploads must be 5 MB or smaller each."
        )

        save = st.form_submit_button("Save Article Changes")

    if save:
        try:
            _rb_save(
                owner_id,
                template_id,
                title,
                body,
                tags,
                uploads,
                post_id=post_id,
                expected_revision=snapshot["revision"],
                remove_image_ids=removals,
            )

        except Exception as error:
            st.error(f"Changes were not saved: {error}")

        else:
            _rb_reload_editor(owner_id, post_id)

            st.session_state[
                f"rb_blog_notice_{owner_id}"
            ] = f"Article #{post_id} updated."

            st.rerun()


def _rb_page(owner_id):
    st.header("Race Blog")
    st.caption(
        "Private articles for your account. "
        "Add tags by typing a tag and pressing Enter."
    )

    notice = st.session_state.pop(
        f"rb_blog_notice_{owner_id}",
        None,
    )

    if notice:
        st.success(notice)

    templates = {
        row["id"]: row
        for row in _rf_templates(owner_id)
    }

    generation_key = f"rb_create_generation_{owner_id}"
    generation = st.session_state.get(generation_key, 0)
    prefix = f"rb_create_{owner_id}_{generation}"

    with st.expander("Write a Race Blog Article", expanded=False):
        if not templates:
            st.info("Create a race template first.")

        else:
            with st.form(prefix):
                template_id = st.selectbox(
                    "Race template for this article",
                    list(templates),
                    format_func=lambda value: _rf_label(
                        templates[value]
                    ),
                    key=prefix + "_template",
                )

                title = st.text_input(
                    "Article title",
                    max_chars=200,
                    key=prefix + "_title",
                )

                body = st.text_area(
                    "Article text — Markdown supported",
                    height=280,
                    max_chars=200_000,
                    key=prefix + "_body",
                )

                tags = _rb_tag_input(
                    owner_id,
                    "Tags — type a tag and press Enter",
                    prefix + "_tags",
                )

                uploads = st.file_uploader(
                    "Images — up to six, 5 MB each",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    key=prefix + "_uploads",
                )

                save = st.form_submit_button("Save Blog Article")

            if save:
                try:
                    post_id = _rb_save(
                        owner_id,
                        template_id,
                        title,
                        body,
                        tags,
                        uploads,
                    )

                except Exception as error:
                    st.error(f"Article was not saved: {error}")

                else:
                    st.session_state[generation_key] = generation + 1

                    st.session_state[
                        f"rb_blog_notice_{owner_id}"
                    ] = f"Article #{post_id} saved."

                    st.rerun()

    st.subheader("Search Articles")

    query = st.text_input(
        "Search titles, article text, or tags",
        key=f"rb_search_text_{owner_id}",
    )

    tag_filter = _rb_tag_input(
        owner_id,
        "Require tags — all selected tags must match",
        f"rb_search_tags_{owner_id}",
    )

    try:
        count, rows = _rb_search(owner_id, query, tag_filter)

    except ValueError as error:
        st.error(str(error))
        return

    st.caption(f"{count:,} matching article(s).")

    if not count:
        return

    page = st.selectbox(
        "Article results page",
        range(1, (count + 19) // 20 + 1),
    )

    if page != 1:
        _, rows = _rb_search(
            owner_id,
            query,
            tag_filter,
            page,
        )

    lookup = {
        row["id"]: row for row in rows
    }

    selected = st.selectbox(
        "Read or edit an article",
        [None] + list(lookup),
        format_func=lambda value: (
            "(Select an article)"
            if value is None
            else (
                f"#{value} | {lookup[value]['title']} | "
                f"{lookup[value]['created_at']}"
            )
        ),
    )

    if selected is None:
        return

    found = _rf_rows(
        "SELECT * FROM rf_blog_posts "
        "WHERE owner_id = ? AND id = ?",
        (owner_id, selected),
    )

    if not found:
        st.info("The article is no longer available.")
        return

    post = found[0]

    st.subheader(post["title"])
    st.caption("Created: " + post["created_at"])

    if post.get("updated_at"):
        st.caption("Updated: " + post["updated_at"])

    template = templates.get(post["template_id"])

    if template:
        st.caption(_rf_label(template))

    tags = _rb_post_tags(owner_id, post["id"])

    if tags:
        # JSON representation distinguishes tags that contain commas.
        st.caption(
            "Tags: " + json.dumps(tags, ensure_ascii=False)
        )

    st.markdown(
        post["body"],
        unsafe_allow_html=False,
    )

    if st.checkbox(
        "Load article images",
        key=f"rb_show_images_{owner_id}_{post['id']}",
    ):
        images = _rf_rows(
            "SELECT filename, image_data FROM rf_blog_images "
            "WHERE owner_id = ? AND post_id = ? ORDER BY id",
            (owner_id, post["id"]),
        )

        if not images:
            st.caption("This article has no images.")

        for image in images:
            st.image(
                bytes(image["image_data"]),
                caption=image["filename"],
            )

    with st.expander("Edit This Article", expanded=False):
        st.caption(
            "Changes affect only this article. "
            "Existing images are retained unless explicitly selected "
            "for removal. Nothing is saved until Save Article Changes."
        )

        _rb_edit_article(
            owner_id,
            post,
            templates,
        )

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


def assignment_names(node):
    if not isinstance(node, ast.Assign):
        return set()

    return {
        item.id
        for target in node.targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name)
    }


def patch_application(source):
    if MARKER in source:
        return source

    tree = ast.parse(source)

    required = {
        "init_db",
        "_rf_blog_page",
        "_rf_db",
        "_rf_rows",
        "_rf_template",
        "_rf_templates",
        "_rf_label",
        "_rf_images",
    }

    functions = {
        name: find_function(tree, name)
        for name in required
    }

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
            "Conflicting blog helper names already exist: "
            + ", ".join(sorted(conflicts))
        )

    initializer = functions["init_db"]
    blog_page = functions["_rf_blog_page"]

    spans = {
        initializer.name: (
            definition_start(initializer),
            initializer.end_lineno,
        ),
        blog_page.name: (
            definition_start(blog_page),
            blog_page.end_lineno,
        ),
    }

    initializer.body.extend(
        ast.parse("_rb_migrate()").body
    )

    # Keep the existing navigation entry and public page function name.
    blog_page.body = ast.parse(
        "_rb_page(owner_id)"
    ).body

    if not any(
        argument.arg == "owner_id"
        for argument in blog_page.args.args
    ):
        raise ValueError(
            "Unexpected race-blog page signature."
        )

    edits = []

    for function in (initializer, blog_page):
        ast.fix_missing_locations(function)
        start, end = spans[function.name]

        edits.append(
            (
                start,
                end,
                ast.unparse(function) + "\n\n",
            )
        )

    edits.sort(key=lambda item: item[0])

    if any(
        right[0] < left[1]
        for left, right in zip(edits, edits[1:])
    ):
        raise ValueError("Overlapping source replacements.")

    lines = source.splitlines(keepends=True)

    for start, end, replacement in reversed(edits):
        lines[start:end] = [replacement]

    intermediate = "".join(lines)
    updated_tree = ast.parse(intermediate)

    first_definition = next(
        (
            node
            for node in updated_tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.ClassDef),
            )
        ),
        None,
    )

    if first_definition is None:
        raise ValueError(
            "Cannot locate a safe helper insertion point."
        )

    lines = intermediate.splitlines(keepends=True)

    lines.insert(
        definition_start(first_definition),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<race-blog-edit-and-enter-tags>",
        "exec",
    )

    permitted = helper_names | {
        "init_db",
        "_rf_blog_page",
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
            "Unexpected changes outside blog integration points."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid blog patch marker.")

    return updated


def database_path(source, application_path, explicit):
    if explicit:
        return Path(explicit).resolve()

    values = [
        node.value.value
        for node in ast.parse(source).body
        if (
            isinstance(node, ast.Assign)
            and "DB_PATH" in assignment_names(node)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]

    if len(values) != 1:
        raise ValueError(
            "Cannot detect DB_PATH. Specify --database PATH."
        )

    path = Path(values[0])

    if path.is_absolute():
        return path.resolve()

    app_relative = (
        application_path.parent / path
    ).resolve()

    cwd_relative = path.resolve()

    if (
        app_relative != cwd_relative
        and app_relative.exists()
        and cwd_relative.exists()
    ):
        raise ValueError(
            "Two possible databases exist. "
            "Specify the correct path with --database."
        )

    return (
        cwd_relative
        if cwd_relative.exists()
        else app_relative
    )


def backup_database(path):
    if not path.exists():
        return None

    backup = path.with_name(
        path.name + ".before-blog-edit-enter-tags.bak"
    )

    if backup.exists():
        raise FileExistsError(
            f"Database backup already exists: {backup}"
        )

    source = None
    destination = None

    try:
        source = sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
            timeout=10,
        )

        destination = sqlite3.connect(backup)
        source.backup(destination)

        result = destination.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if not result or result[0] != "ok":
            raise RuntimeError(
                "Database backup integrity check failed."
            )

    except Exception:
        if destination is not None:
            destination.close()
            destination = None

        if backup.exists():
            backup.unlink()

        raise

    finally:
        if source is not None:
            source.close()

        if destination is not None:
            destination.close()

    return backup


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add race-blog article editing and "
            "Enter-key tag entry."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    parser.add_argument(
        "--database",
        help="Explicit database path to back up.",
    )

    arguments = parser.parse_args()
    app_path = Path(arguments.app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    source = app_path.read_text(
        encoding="utf-8-sig"
    )

    if MARKER in source:
        print(
            f"The blog editing update is already installed: {app_path}"
        )
        return

    try:
        updated = patch_application(source)

        database = database_path(
            source,
            app_path,
            arguments.database,
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    source_backup = app_path.with_name(
        app_path.name + ".before-blog-edit-enter-tags.bak"
    )

    if source_backup.exists():
        raise SystemExit(
            f"Source backup already exists: {source_backup}\n"
            "Move or rename it before retrying."
        )

    try:
        db_backup = backup_database(database)
        shutil.copy2(app_path, source_backup)

    except Exception as error:
        raise SystemExit(
            "Backup failed. Application source was not changed.\n"
            f"{error}"
        ) from error

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
            temporary_path = Path(
                temporary_file.name
            )
            temporary_file.write(updated)

        shutil.copymode(
            app_path,
            temporary_path,
        )

        temporary_path.replace(app_path)

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Source backup: {source_backup}")
    print(f"Database path: {database}")
    print(
        "Database backup: "
        + (
            str(db_backup)
            if db_backup
            else "No existing database at the detected path"
        )
    )
    print("Python syntax and AST-scope validation passed.")
    print("Restart the application to run the blog schema migration.")
    print("Articles can now be edited from Edit This Article.")
    print("Tags use Enter-key entry, not comma-separated entry.")
    print("Older Streamlit versions use one tag per line.")
    print("Existing images are preserved unless explicitly removed.")
    print("Concurrent article changes are checked before saving.")
    print("Existing articles, tags, and template links are preserved.")
    print("Interactive browser testing remains required.")


if __name__ == "__main__":
    main()
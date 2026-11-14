# scripts/implement-race-blog.py
#
# Replaces the Race Blog article-selection dropdown with
# 20 visible article cards per page.
#
# Adds:
#   - Title, dates, race details, tags, and text preview per article
#   - Previous/Next controls at the top and bottom
#   - Direct page-number input
#   - Full-article reading, images, and editing per article
#
# Preserves:
#   - Existing article creation
#   - Enter-key tag entry and tag filtering
#   - Article editing and image storage
#   - Templates, checklists, filters, and Memo display
#
# Requires the earlier scripts/implement-blog-feature.py update.
#
# Safety:
#   - Source backup before replacement
#   - Syntax and AST change-scope validation
#   - Repeat-run detection
#   - No database migration or database writes by this patch script
#
# Stop Streamlit before running:
#   python scripts/implement-race-blog.py app.py

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# RACE_BLOG_VISIBLE_LIST_PAGINATION_V1"


RUNTIME = r'''
# RACE_BLOG_VISIBLE_LIST_PAGINATION_V1

def _rbl_move(owner_id, amount, total_pages):
    key = f"rbl_page_{owner_id}"
    current = int(st.session_state.get(key, 1) or 1)

    st.session_state[key] = max(
        1,
        min(total_pages, current + amount),
    )


def _rbl_navigation(owner_id, page, total_pages, position):
    left, middle, right = st.columns([1, 2, 1])

    with left:
        st.button(
            "Previous",
            key=f"rbl_previous_{position}_{owner_id}",
            disabled=page <= 1,
            on_click=_rbl_move,
            args=(owner_id, -1, total_pages),
        )

    with middle:
        if position == "top":
            page = int(
                st.number_input(
                    "Page",
                    min_value=1,
                    max_value=total_pages,
                    step=1,
                    value=None,
                    key=f"rbl_page_{owner_id}",
                )
                or 1
            )

        st.caption(
            f"Page {page:,} of {total_pages:,}"
            " · 20 articles per page"
        )

    with right:
        st.button(
            "Next",
            key=f"rbl_next_{position}_{owner_id}",
            disabled=page >= total_pages,
            on_click=_rbl_move,
            args=(owner_id, 1, total_pages),
        )

    return page


def _rbl_render(owner_id, templates):
    import json

    st.subheader("Articles")

    query = st.text_input(
        "Search titles, article text, or tags",
        key=f"rbl_search_text_{owner_id}",
    )

    tags = _rb_tag_input(
        owner_id,
        "Require tags — all selected tags must match",
        f"rbl_search_tags_{owner_id}",
    )

    try:
        normalized_tags = _rb_tags(tags)

        signature = json.dumps(
            [
                query.strip(),
                sorted(normalized_tags),
            ],
            ensure_ascii=False,
        )

        # The existing search helper returns 20 articles per page.
        count, rows = _rb_search(
            owner_id,
            query,
            tags,
            page=1,
        )

    except ValueError as error:
        st.error(str(error))
        return

    page_key = f"rbl_page_{owner_id}"
    signature_key = f"rbl_signature_{owner_id}"

    # Start from page one when search conditions change.
    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[page_key] = 1

    total_pages = max(1, (count + 19) // 20)

    page = max(
        1,
        min(
            total_pages,
            int(st.session_state.get(page_key, 1) or 1),
        ),
    )

    # Set state before creating the page-number widget.
    st.session_state[page_key] = page

    if not count:
        st.info(
            "No articles match these search conditions."
        )
        return

    page = _rbl_navigation(
        owner_id,
        page,
        total_pages,
        "top",
    )

    if page != 1:
        count, rows = _rb_search(
            owner_id,
            query,
            tags,
            page=page,
        )

    if not rows:
        st.info(
            "The results changed. Use Previous or change "
            "the search to refresh the list."
        )
        return

    first = (page - 1) * 20 + 1
    last = first + len(rows) - 1

    st.caption(
        f"Showing articles {first:,}–{last:,} "
        f"of {count:,}. Newest first."
    )

    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)

    # Fetch article text only for the current page.
    posts = {
        row["id"]: row
        for row in _rf_rows(
            "SELECT * FROM rf_blog_posts "
            "WHERE owner_id=? AND id IN ("
            + placeholders
            + ")",
            [owner_id] + ids,
        )
    }

    # Fetch tags for the current page in one query.
    tag_rows = _rf_rows(
        "SELECT pt.post_id,t.name "
        "FROM rf_blog_post_tags pt "
        "JOIN rf_blog_tags t ON t.id=pt.tag_id "
        "JOIN rf_blog_posts p ON p.id=pt.post_id "
        "WHERE p.owner_id=? AND t.owner_id=? "
        "AND p.id IN ("
        + placeholders
        + ") ORDER BY t.normalized",
        [owner_id, owner_id] + ids,
    )

    tags_by_post = {}

    for row in tag_rows:
        tags_by_post.setdefault(
            row["post_id"],
            [],
        ).append(row["name"])

    # Preserve the ordering returned by the search helper.
    for result in rows:
        post = posts.get(result["id"])

        if post is None:
            continue

        post_id = post["id"]
        prefix = f"rbl_article_{owner_id}_{post_id}"

        with st.container(border=True):
            st.subheader(post["title"])

            dates = (
                f"Article #{post_id}"
                f" | Created: {post['created_at']}"
            )

            if post.get("updated_at"):
                dates += (
                    f" | Updated: {post['updated_at']}"
                )

            st.caption(dates)

            template = templates.get(
                post["template_id"]
            )

            if template:
                st.caption(_rf_label(template))

            else:
                st.caption(
                    "Associated race template is unavailable."
                )

            article_tags = tags_by_post.get(
                post_id,
                [],
            )

            if article_tags:
                st.caption(
                    "Tags: "
                    + json.dumps(
                        article_tags,
                        ensure_ascii=False,
                    )
                )

            body = post.get("body") or ""

            if len(body) <= 500:
                st.markdown(
                    body,
                    unsafe_allow_html=False,
                )

            else:
                # A plain-text preview avoids broken Markdown
                # caused by cutting a link or formatting token.
                st.text(
                    body[:500].rstrip() + "…"
                )

                if st.checkbox(
                    "Read full article",
                    key=prefix + "_full",
                ):
                    st.markdown(
                        body,
                        unsafe_allow_html=False,
                    )

            if st.checkbox(
                "Show images",
                key=prefix + "_images",
            ):
                images = _rf_rows(
                    "SELECT filename,image_data "
                    "FROM rf_blog_images "
                    "WHERE owner_id=? AND post_id=? "
                    "ORDER BY id",
                    (owner_id, post_id),
                )

                if not images:
                    st.caption(
                        "This article has no images."
                    )

                for image in images:
                    st.image(
                        bytes(image["image_data"]),
                        caption=image["filename"],
                    )

            if st.checkbox(
                "Edit this article",
                key=prefix + "_edit",
            ):
                _rb_edit_article(
                    owner_id,
                    post,
                    templates,
                )

    _rbl_navigation(
        owner_id,
        page,
        total_pages,
        "bottom",
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


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)

    required = {
        "_rb_page",
        "_rb_search",
        "_rb_tags",
        "_rb_tag_input",
        "_rb_edit_article",
        "_rf_rows",
        "_rf_label",
    }

    functions = {
        name: find_function(tree, name)
        for name in required
    }

    page = functions["_rb_page"]

    if not any(
        argument.arg == "owner_id"
        for argument in page.args.args
    ):
        raise ValueError(
            "Unexpected Race Blog page signature."
        )

    anchors = [
        index
        for index, node in enumerate(page.body)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(
                node.value.func,
                ast.Attribute,
            )
            and isinstance(
                node.value.func.value,
                ast.Name,
            )
            and node.value.func.value.id == "st"
            and node.value.func.attr == "subheader"
            and node.value.args
            and isinstance(
                node.value.args[0],
                ast.Constant,
            )
            and node.value.args[0].value
            == "Search Articles"
        )
    ]

    if len(anchors) != 1:
        raise ValueError(
            "Cannot identify the existing article-search "
            "and dropdown section. Application was not changed."
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

    conflicts = helper_names.intersection(
        existing_names
    )

    if conflicts:
        raise ValueError(
            "Conflicting blog-list helpers exist: "
            + ", ".join(sorted(conflicts))
        )

    start = definition_start(page)
    end = page.end_lineno

    # Preserve the existing heading, notifications, template
    # lookup, and article-creation form. Replace only the old
    # search/dropdown/viewer tail.
    page.body = (
        page.body[:anchors[0]]
        + ast.parse(
            "_rbl_render(owner_id, templates)"
        ).body
    )

    ast.fix_missing_locations(page)

    lines = source.splitlines(
        keepends=True
    )

    lines[start:end] = [
        ast.unparse(page) + "\n\n"
    ]

    intermediate = "".join(lines)
    intermediate_tree = ast.parse(
        intermediate
    )

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

    lines = intermediate.splitlines(
        keepends=True
    )

    lines.insert(
        definition_start(first_definition),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<race-blog-visible-list>",
        "exec",
    )

    permitted = helper_names | {
        "_rb_page"
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
            "the Race Blog list integration."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid blog-list patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Display 20 Race Blog article cards per page "
            "instead of an article-selection dropdown."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    arguments = parser.parse_args()
    app_path = Path(
        arguments.app_file
    ).resolve()

    if not app_path.is_file():
        raise SystemExit(
            f"Application file not found: {app_path}"
        )

    original_bytes = app_path.read_bytes()

    try:
        source = original_bytes.decode(
            "utf-8-sig"
        )

        updated, changed = patch_application(
            source
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}\n"
            "This script requires the earlier "
            "implement-blog-feature.py update."
        ) from error

    if not changed:
        print(
            "The paginated Race Blog list "
            "is already installed. No changes were made."
        )
        return

    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup_path = app_path.with_name(
        f"{app_path.name}."
        f"before-blog-pagination-{timestamp}.bak"
    )

    temporary_path = None

    try:
        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed during validation. "
                "Run the patch again."
            )

        shutil.copy2(
            app_path,
            backup_path,
        )

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

            temporary_file.write(
                updated
            )

        shutil.copymode(
            app_path,
            temporary_path,
        )

        if app_path.read_bytes() != original_bytes:
            raise RuntimeError(
                "Application source changed before replacement. "
                "Run the patch again."
            )

        temporary_path.replace(
            app_path
        )

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
    print(
        "Python syntax and AST-scope validation passed."
    )
    print(
        "The article-selection dropdown was replaced "
        "with visible article cards."
    )
    print(
        "Page size: 20 articles, with fewer on "
        "the final page when appropriate."
    )
    print(
        "Previous/Next controls appear above "
        "and below the list."
    )
    print(
        "Search changes reset pagination to page one."
    )
    print(
        "Article creation, Enter-key tags, editing, "
        "and images remain available."
    )
    print(
        "No database records or schema were changed."
    )
    print(
        "Restart Streamlit and open Race Blog."
    )
    print(
        "Interactive browser testing remains required."
    )


if __name__ == "__main__":
    main()
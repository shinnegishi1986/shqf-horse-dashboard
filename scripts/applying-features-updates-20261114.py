# scripts/applying-features-updates-20261114.py
# Complete feature updater matched to the supplied app.py.
# Stop Streamlit before running.
# python scripts/applying-features-updates-20261114.py app.py
# Optional: --database data/horse_checklist_app.db
# No database migrations run until the patched app starts.

RUNTIME = r'''
# RACE_FEATURES_20261114_V2
_RF_UNSET = object()


def _rf_db():
    conn = get_db_connection()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("RF_CASEFOLD", 1, lambda x: str(x or "").casefold())
    return conn


def _rf_rows(sql, args=()):
    conn = _rf_db()
    try:
        return [dict(row) for row in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _rf_migrate():
    conn = _rf_db()
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='rf_versions' AND type='table'").fetchone()
        if exists and conn.execute("SELECT 1 FROM rf_versions WHERE version='20261114-v2'").fetchone():
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS race_classes (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL REFERENCES users(id), race_class_name TEXT NOT NULL, UNIQUE(owner_id,race_class_name))")
            if "race_class_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(checklists)")}:
                conn.execute("ALTER TABLE checklists ADD COLUMN race_class_id INTEGER REFERENCES race_classes(id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rf_checklist_class ON checklists(owner_id,race_class_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS rf_race_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                race_name_id INTEGER NOT NULL REFERENCES race_names(id),
                race_date TEXT NOT NULL,
                program_number INTEGER NOT NULL CHECK(program_number BETWEEN 1 AND 12),
                distance INTEGER NOT NULL CHECK(distance BETWEEN 1 AND 5000),
                number_of_horses INTEGER NOT NULL CHECK(number_of_horses BETWEEN 1 AND 18),
                race_class_id INTEGER REFERENCES race_classes(id),
                UNIQUE(owner_id,race_name_id,race_date,program_number))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rf_blog_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                template_id INTEGER NOT NULL REFERENCES rf_race_templates(id),
                title TEXT NOT NULL, body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rf_blog_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, normalized TEXT NOT NULL,
                UNIQUE(owner_id,normalized))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rf_blog_post_tags (
                post_id INTEGER NOT NULL REFERENCES rf_blog_posts(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES rf_blog_tags(id),
                PRIMARY KEY(post_id,tag_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rf_blog_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                post_id INTEGER NOT NULL REFERENCES rf_blog_posts(id) ON DELETE CASCADE,
                filename TEXT NOT NULL, mime_type TEXT NOT NULL, image_data BLOB NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rf_posts_owner ON rf_blog_posts(owner_id,id DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rf_images_post ON rf_blog_images(owner_id,post_id)")
            conn.execute("CREATE TABLE IF NOT EXISTS rf_versions(version TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO rf_versions(version) VALUES ('20261114-v2')")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _rf_class_options(owner_id):
    rows = _rf_rows("SELECT id,race_class_name FROM race_classes WHERE owner_id=? ORDER BY race_class_name COLLATE NOCASE,id", (owner_id,))
    return [None] + [r["id"] for r in rows], ["(No selection)"] + [r["race_class_name"] for r in rows]


def _rf_class_select(owner_id, key, current=None):
    ids, labels = _rf_class_options(owner_id)
    current = current if current in ids else None
    return st.selectbox("Race Class", ids,
        index=None if key in st.session_state else ids.index(current),
        format_func=lambda value: labels[ids.index(value)], key=key)


def _rf_resolve_class(owner_id, checklist_id, value):
    if value is _RF_UNSET:
        if checklist_id is None:
            return None
        rows = _rf_rows("SELECT race_class_id FROM checklists WHERE owner_id=? AND id=?", (owner_id,checklist_id))
        return rows[0]["race_class_id"] if rows else None
    if value is not None and not _rf_rows("SELECT id FROM race_classes WHERE owner_id=? AND id=?", (owner_id,value)):
        raise ValueError("The selected race class does not belong to this account.")
    return value


def _rf_enrich(function):
    import functools
    @functools.wraps(function)
    def wrapped(owner_id, *args, **kwargs):
        records = function(owner_id, *args, **kwargs)
        rows = _rf_rows("""SELECT c.id,c.race_class_id,rc.race_class_name FROM checklists c
            LEFT JOIN race_classes rc ON rc.id=c.race_class_id AND rc.owner_id=c.owner_id
            WHERE c.owner_id=?""", (owner_id,))
        extra = {r["id"]:r for r in rows}
        for entry in records:
            value = extra.get(entry["id"], {})
            entry["race_class_id"] = value.get("race_class_id")
            entry["race_class_name"] = value.get("race_class_name") or ""
        return records
    return wrapped


def _rf_classes_page(owner_id):
    st.header("Race Classes")
    with st.form(f"rf_add_class_{owner_id}", clear_on_submit=True):
        name = st.text_input("New race class", max_chars=100)
        submitted = st.form_submit_button("Register Race Class")
    if submitted:
        if not name.strip():
            st.error("Enter a race-class name.")
        else:
            conn = _rf_db()
            try:
                with conn:
                    conn.execute("INSERT INTO race_classes(owner_id,race_class_name) VALUES (?,?)", (owner_id,name.strip()))
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("This race class is already registered.")
            finally:
                conn.close()
    rows = _rf_rows("SELECT id,race_class_name FROM race_classes WHERE owner_id=? ORDER BY race_class_name", (owner_id,))
    for row in rows:
        with st.expander(row["race_class_name"]):
            with st.form(f"rf_rename_class_{owner_id}_{row['id']}"):
                name = st.text_input("Race-class name", value=row["race_class_name"], max_chars=100)
                rename = st.form_submit_button("Rename Race Class")
            if rename:
                if not name.strip():
                    st.error("Enter a race-class name.")
                    continue
                conn = _rf_db()
                try:
                    with conn:
                        conn.execute("UPDATE race_classes SET race_class_name=? WHERE owner_id=? AND id=?", (name.strip(),owner_id,row["id"]))
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("This race class already exists.")
                finally:
                    conn.close()
    st.caption("Renaming preserves associations. Class deletion is not enabled.")


def _rf_templates(owner_id):
    return _rf_rows("""SELECT t.*,rn.race_name,rc.race_class_name FROM rf_race_templates t
        LEFT JOIN race_names rn ON rn.id=t.race_name_id AND rn.owner_id=t.owner_id
        LEFT JOIN race_classes rc ON rc.id=t.race_class_id AND rc.owner_id=t.owner_id
        WHERE t.owner_id=? ORDER BY t.race_date DESC,t.program_number,t.id DESC""", (owner_id,))


def _rf_label(row):
    return (f"{row['race_date']} | R{row['program_number']} | "
        f"{row.get('race_name') or '(Race name unavailable)'} | "
        f"{row['distance']}m | {row['number_of_horses']} horses"
        + (f" | {row['race_class_name']}" if row.get("race_class_name") else ""))


def _rf_template(owner_id, template_id):
    row = next((r for r in _rf_templates(owner_id) if r["id"] == template_id), None)
    if row is None or not row.get("race_name"):
        raise ValueError("The race template or its race name is unavailable.")
    _rf_resolve_class(owner_id, None, row["race_class_id"])
    return row


def _rf_save_template(owner_id, name_id, new_name, race_date, program, distance, horses, class_id):
    if not 1 <= int(program) <= 12 or not 1 <= int(distance) <= 5000 or not 1 <= int(horses) <= 18:
        raise ValueError("Race template numbers are outside the supported ranges.")
    if not date(1980,1,1) <= race_date <= date(2100,12,31):
        raise ValueError("Race date must be between 1980 and 2100.")
    _rf_resolve_class(owner_id, None, class_id)
    conn = _rf_db()
    try:
        with conn:
            if name_id is None:
                name = new_name.strip()
                if not name or len(name)>200:
                    raise ValueError("Enter a race name of 1–200 characters.")
                found = conn.execute("SELECT id FROM race_names WHERE owner_id=? AND RF_CASEFOLD(race_name)=RF_CASEFOLD(?)", (owner_id,name)).fetchone()
                name_id = found["id"] if found else conn.execute("INSERT INTO race_names(owner_id,race_name) VALUES (?,?)", (owner_id,name)).lastrowid
            elif not conn.execute("SELECT 1 FROM race_names WHERE owner_id=? AND id=?", (owner_id,name_id)).fetchone():
                raise ValueError("Race name does not belong to this account.")
            conn.execute("""INSERT INTO rf_race_templates
                (owner_id,race_name_id,race_date,program_number,distance,number_of_horses,race_class_id)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(owner_id,race_name_id,race_date,program_number) DO UPDATE SET
                distance=excluded.distance,number_of_horses=excluded.number_of_horses,race_class_id=excluded.race_class_id""",
                (owner_id,name_id,race_date.isoformat(),int(program),int(distance),int(horses),class_id))
    finally:
        conn.close()


def _rf_templates_page(owner_id):
    st.header("Race Templates")
    names = {r["id"]:r["race_name"] for r in get_user_race_names(owner_id)}
    st.caption("Saving the same race name, date, and program number updates that template. Existing checklist records do not change.")
    with st.form(f"rf_template_form_{owner_id}"):
        name_id = st.selectbox("Existing race name", [None]+list(names), format_func=lambda x: "(Create a new race name)" if x is None else names[x])
        name = st.text_input("New race name — used only for Create a new race name", max_chars=200)
        race_date = st.date_input("Race date", value=date.today(), min_value=date(1980,1,1), max_value=date(2100,12,31))
        program = st.number_input("Program number", min_value=1, max_value=12, value=1)
        distance = st.number_input("Distance (meters)", min_value=1, max_value=5000, value=1600, step=100)
        horses = st.number_input("Number of horses", min_value=1, max_value=18, value=18)
        class_id = _rf_class_select(owner_id, f"rf_template_class_{owner_id}")
        submitted = st.form_submit_button("Save Race Template")
    if submitted:
        try:
            _rf_save_template(owner_id,name_id,name,race_date,program,distance,horses,class_id)
            st.success("Race template saved.")
        except (ValueError,sqlite3.Error) as error:
            st.error(f"Could not save template: {error}")
    rows = _rf_templates(owner_id)
    if rows:
        st.dataframe(pd.DataFrame([{"ID":r["id"],"Date":r["race_date"],"Race":r["race_name"] or "","Program":r["program_number"],"Distance":r["distance"],"Horses":r["number_of_horses"],"Class":r["race_class_name"] or ""} for r in rows]), hide_index=True, width="stretch")
    else:
        st.info("No race templates registered yet.")


def _rf_seeded_widget(widget_function, *args, **kwargs):
    key = kwargs.get("key")
    if key is not None and key in st.session_state:
        kwargs["value"] = None
    return widget_function(*args, **kwargs)


def _rf_load(owner_id, template_id, mode, target_keys=None):
    try:
        row = _rf_template(owner_id,template_id)
        if mode == "registration":
            values = {"selected_race_idx":row["race_name"], "date_of_race":date.fromisoformat(row["race_date"]),
                "program_number":row["program_number"], "distance":row["distance"],
                "number_of_horses":row["number_of_horses"], "race_class_id":row["race_class_id"]}
            if not target_keys or any(field not in target_keys for field in values):
                raise ValueError("Registration widget mapping is incomplete.")
            for field,value in values.items():
                st.session_state[target_keys[field]] = value
            # The older-browser reference helper gives this text box priority.
            st.session_state[target_keys["selected_race_idx"] + "_new_name"] = ""
        else:
            reset_filter_values(owner_id)
            values = {"race_name_id":row["race_name_id"], "race_class_id":row["race_class_id"],
                "date_from":date.fromisoformat(row["race_date"]), "date_to":date.fromisoformat(row["race_date"]),
                "program_number":row["program_number"], "number_of_horses":row["number_of_horses"],
                "distance_from":row["distance"], "distance_to":row["distance"], "enable_distance_filter":True,
                "page_number":1, "active_filter_title":"Race template: " + _rf_label(row)}
            for field,value in values.items():
                st.session_state[saved_filter_key(owner_id,field)] = value
            st.session_state[filter_load_version_key(owner_id)] += 1
            st.session_state[second_filter_key(owner_id,"enabled")] = False
            st.session_state.pop(_review_filter_restore_key(owner_id),None)
            st.session_state.pop("selected_review_checklist_id",None)
        st.session_state[f"rf_notice_{mode}_{owner_id}"] = "Loaded: " + _rf_label(row)
    except (ValueError,sqlite3.Error) as error:
        st.session_state[f"rf_error_{mode}_{owner_id}"] = str(error)


def _rf_loader(owner_id, mode, target_keys=None):
    notice = st.session_state.pop(f"rf_notice_{mode}_{owner_id}",None)
    error = st.session_state.pop(f"rf_error_{mode}_{owner_id}",None)
    if notice:
        st.success(notice)
    if error:
        st.error(error)
    with st.expander("Load Race Template", expanded=False):
        rows = _rf_templates(owner_id)
        if not rows:
            st.info("Create a race template from the Race Templates menu.")
            return
        lookup = {r["id"]:r for r in rows}
        selected = st.selectbox("Race template", [None]+list(lookup), format_func=lambda x: "(Select a template)" if x is None else _rf_label(lookup[x]), key=f"rf_loader_{mode}_{owner_id}")
        st.caption("Load replaces first-filter conditions with this race's settings and disables the second filter." if mode=="review" else "Load fills race fields. It does not save a checklist.")
        st.button("Load Race Template", key=f"rf_load_button_{mode}_{owner_id}", disabled=selected is None, on_click=_rf_load, args=(owner_id,selected,mode,target_keys))


def _rf_tags(text):
    tags = {}
    for part in text.split(","):
        value = part.strip()
        if not value:
            continue
        if len(value)>60:
            raise ValueError("Each tag must be 60 characters or fewer.")
        tags.setdefault(value.casefold(),value)
    if len(tags)>20:
        raise ValueError("Use no more than 20 tags.")
    return tags


def _rf_images(uploads):
    import io
    import warnings
    from pathlib import Path
    from PIL import Image, ImageOps
    if len(uploads)>6:
        raise ValueError("Upload no more than six images.")
    prepared, total = [], 0
    for upload in uploads:
        raw = upload.getvalue()
        if not raw or len(raw)>5*1024*1024:
            raise ValueError("Each image must be nonempty and no larger than 5 MB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG","PNG","WEBP"} or image.width*image.height>20_000_000:
                    raise ValueError("Use JPEG/PNG/WebP images no larger than 20 megapixels.")
                image.verify()
            with Image.open(io.BytesIO(raw)) as original:
                image = ImageOps.exif_transpose(original)
                image.load()
                alpha = image.mode in {"RGBA","LA"} or "transparency" in image.info
                # A fresh image avoids retaining uploaded metadata.
                pixels = image.convert("RGBA" if alpha else "RGB")
                clean = Image.new(pixels.mode,pixels.size)
                clean.paste(pixels)
                output = io.BytesIO()
                clean.save(output,format="PNG" if alpha else "JPEG",**({} if alpha else {"quality":90}))
        data = output.getvalue()
        total += len(data)
        if total>20*1024*1024:
            raise ValueError("Combined processed images must not exceed 20 MB.")
        name = Path(upload.name.replace("\\","/").split("/")[-1]).stem[:160] or "image"
        prepared.append((name+(".png" if alpha else ".jpg"), "image/png" if alpha else "image/jpeg",data))
    return prepared


def _rf_save_post(owner_id,template_id,title,body,tag_text,uploads):
    title, body = title.strip(), body.strip()
    if not title or not body or len(title)>200 or len(body)>200_000:
        raise ValueError("Enter a title (1–200 characters) and article text (1–200,000 characters).")
    tags, images = _rf_tags(tag_text), _rf_images(uploads)
    _rf_template(owner_id,template_id)
    conn = _rf_db()
    try:
        with conn:
            if not conn.execute("SELECT 1 FROM rf_race_templates WHERE owner_id=? AND id=?", (owner_id,template_id)).fetchone():
                raise ValueError("Race template is unavailable.")
            post_id = conn.execute("INSERT INTO rf_blog_posts(owner_id,template_id,title,body) VALUES (?,?,?,?)", (owner_id,template_id,title,body)).lastrowid
            for normalized,name in tags.items():
                conn.execute("INSERT INTO rf_blog_tags(owner_id,name,normalized) VALUES (?,?,?) ON CONFLICT(owner_id,normalized) DO NOTHING", (owner_id,name,normalized))
                tag_id = conn.execute("SELECT id FROM rf_blog_tags WHERE owner_id=? AND normalized=?", (owner_id,normalized)).fetchone()["id"]
                conn.execute("INSERT INTO rf_blog_post_tags(post_id,tag_id) VALUES (?,?)", (post_id,tag_id))
            for name,mime,data in images:
                conn.execute("INSERT INTO rf_blog_images(owner_id,post_id,filename,mime_type,image_data) VALUES (?,?,?,?,?)", (owner_id,post_id,name,mime,sqlite3.Binary(data)))
        return post_id
    finally:
        conn.close()


def _rf_search(owner_id,query,tag_text,page=1):
    tags = _rf_tags(tag_text)
    clauses, args = ["p.owner_id=?"], [owner_id]
    if query.strip():
        clauses.append("""(instr(RF_CASEFOLD(p.title||' '||p.body),RF_CASEFOLD(?))>0 OR EXISTS (
            SELECT 1 FROM rf_blog_post_tags pt JOIN rf_blog_tags tg ON tg.id=pt.tag_id
            WHERE pt.post_id=p.id AND tg.owner_id=p.owner_id AND instr(tg.normalized,RF_CASEFOLD(?))>0))""")
        args.extend([query.strip(),query.strip()])
    for tag in tags:
        clauses.append("""EXISTS (SELECT 1 FROM rf_blog_post_tags pt JOIN rf_blog_tags tg ON tg.id=pt.tag_id
            WHERE pt.post_id=p.id AND tg.owner_id=p.owner_id AND tg.normalized=?)""")
        args.append(tag)
    where = " AND ".join(clauses)
    count = _rf_rows("SELECT COUNT(*) n FROM rf_blog_posts p WHERE "+where,args)[0]["n"]
    rows = _rf_rows("SELECT p.id,p.title,p.created_at FROM rf_blog_posts p WHERE "+where+" ORDER BY p.id DESC LIMIT 20 OFFSET ?", args+[max(0,page-1)*20])
    return count,rows


def _rf_blog_page(owner_id):
    st.header("Race Blog")
    st.caption("Private to your account. Uploaded images are stored in SQLite, not as filesystem image files.")
    templates = {r["id"]:r for r in _rf_templates(owner_id)}
    revision_key = f"rf_blog_revision_{owner_id}"
    revision = st.session_state.get(revision_key,0)
    message = st.session_state.pop(f"rf_blog_notice_{owner_id}",None)
    if message:
        st.success(message)
    with st.expander("Write a Race Blog Article", expanded=False):
        if not templates:
            st.info("Create a race template first.")
        else:
            with st.form(f"rf_blog_form_{owner_id}_{revision}"):
                template_id = st.selectbox("Race template for article",list(templates),format_func=lambda x:_rf_label(templates[x]))
                title = st.text_input("Article title",max_chars=200)
                body = st.text_area("Article text — Markdown supported",height=260,max_chars=200_000)
                tags = st.text_input("Tags — comma separated")
                uploads = st.file_uploader("Images — up to six; 5 MB each",type=["jpg","jpeg","png","webp"],accept_multiple_files=True)
                save = st.form_submit_button("Save Blog Article")
            if save:
                try:
                    post_id = _rf_save_post(owner_id,template_id,title,body,tags,uploads)
                except Exception as error:
                    st.error(f"Article was not saved: {error}")
                else:
                    st.session_state[revision_key] = revision+1
                    st.session_state[f"rf_blog_notice_{owner_id}"] = f"Article #{post_id} saved."
                    st.rerun()
    query = st.text_input("Search article titles, text, or tags",key=f"rf_blog_search_{owner_id}")
    tag_query = st.text_input("Require tags — comma separated; all must match",key=f"rf_blog_tag_query_{owner_id}")
    try:
        count,rows = _rf_search(owner_id,query,tag_query)
    except ValueError as error:
        st.error(str(error))
        return
    st.caption(f"{count:,} matching article(s).")
    if not count:
        return
    page = st.selectbox("Article results page",range(1,(count+19)//20+1))
    if page!=1:
        _,rows = _rf_search(owner_id,query,tag_query,page)
    lookup = {r["id"]:r for r in rows}
    selected = st.selectbox("Read an article",[None]+list(lookup),format_func=lambda x:"(Select an article)" if x is None else f"{lookup[x]['created_at']} | {lookup[x]['title']}")
    if selected is None:
        return
    found = _rf_rows("SELECT * FROM rf_blog_posts WHERE owner_id=? AND id=?",(owner_id,selected))
    if not found:
        st.info("Article no longer exists.")
        return
    post = found[0]
    st.subheader(post["title"])
    st.caption(post["created_at"])
    if post["template_id"] in templates:
        st.caption(_rf_label(templates[post["template_id"]]))
    tag_rows = _rf_rows("""SELECT tg.name FROM rf_blog_post_tags pt JOIN rf_blog_tags tg ON tg.id=pt.tag_id
        JOIN rf_blog_posts p ON p.id=pt.post_id WHERE p.owner_id=? AND p.id=? AND tg.owner_id=? ORDER BY tg.normalized""",(owner_id,selected,owner_id))
    if tag_rows:
        st.caption("Tags: "+", ".join(r["name"] for r in tag_rows))
    st.markdown(post["body"],unsafe_allow_html=False)
    if st.checkbox("Load article images",key=f"rf_blog_images_{owner_id}_{selected}"):
        images = _rf_rows("SELECT filename,image_data FROM rf_blog_images WHERE owner_id=? AND post_id=? ORDER BY id",(owner_id,selected))
        if not images:
            st.caption("This article has no images.")
        for image in images:
            st.image(bytes(image["image_data"]),caption=image["filename"])
'''


import argparse
import ast
import copy
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

MARKER = "# RACE_FEATURES_20261114_V2"


def _fn(tree, name):
    found = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(found)!=1:
        raise ValueError(f"Expected one {name}; found {len(found)}.")
    return found[0]


def _stmts(code):
    return ast.parse(code).body


def _names(node):
    return {n.id for target in node.targets for n in ast.walk(target) if isinstance(n,ast.Name)} if isinstance(node,ast.Assign) else set()


def _start(fn):
    return min([fn.lineno]+[d.lineno for d in fn.decorator_list])-1


def _field(fn, required, name, expression):
    rows = [n for n in ast.walk(fn) if isinstance(n,ast.Dict) and required.issubset({k.value for k in n.keys if isinstance(k,ast.Constant)})]
    if len(rows)!=1:
        raise ValueError(f"Cannot identify the required dictionary in {fn.name}.")
    row = rows[0]
    if any(isinstance(k,ast.Constant) and k.value==name for k in row.keys):
        raise ValueError(f"{name} already exists in {fn.name}.")
    row.keys.append(ast.Constant(name))
    row.values.append(ast.parse(expression,mode="eval").body)


def _body(fn, visitor):
    output = []
    for node in fn.body:
        result = visitor.visit(node)
        if result is not None:
            output.extend(result if isinstance(result,list) else [result])
    fn.body = output


class _PageVisitor(ast.NodeTransformer):
    def visit_FunctionDef(self,node):
        return node
    def visit_AsyncFunctionDef(self,node):
        return node


class _Registration(_PageVisitor):
    fields = {"selected_race_idx","distance","date_of_race","program_number","number_of_horses"}
    def __init__(self):
        self.keys = {}
        self.saves = 0
    def visit_Assign(self,node):
        matches = self.fields.intersection(_names(node))
        if not matches:
            return self.generic_visit(node)
        if len(matches)!=1 or not isinstance(node.value,ast.Call):
            raise ValueError("Unexpected registration field assignment.")
        field = next(iter(matches))
        if field in self.keys:
            raise ValueError(f"Duplicate registration field: {field}")
        call = node.value
        key = next((k.value for k in call.keywords if k.arg=="key"),None)
        if key is None:
            raise ValueError(f"Registration field {field} has no explicit widget key.")
        self.keys[field] = copy.deepcopy(key)
        if field=="selected_race_idx":
            if not isinstance(call.func,ast.Name) or call.func.id!="render_race_reference_input":
                raise ValueError("This updater expects your render_race_reference_input race-name field.")
            return [node]+_stmts("rf_registration_class_id = _rf_class_select(owner_id, registration_key('race_class_id'))")
        method = "date_input" if field=="date_of_race" else "number_input"
        if not (isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=="st" and call.func.attr==method and len(call.args)<=1):
            raise ValueError(f"Unexpected widget structure for {field}.")
        node.value = ast.Call(func=ast.Name(id="_rf_seeded_widget",ctx=ast.Load()),args=[call.func,*call.args],keywords=call.keywords)
        return node
    def visit_Call(self,node):
        self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=="add_checklist":
            node.keywords.append(ast.keyword(arg="race_class_id",value=ast.Name(id="rf_registration_class_id",ctx=ast.Load())))
            self.saves += 1
        return node


class _Editor(_PageVisitor):
    def __init__(self):
        self.widgets = self.saves = 0
    def visit_Assign(self,node):
        self.generic_visit(node)
        if "edit_race_idx" in _names(node):
            self.widgets += 1
            return [node]+_stmts('rf_editor_class_id = _rf_class_select(owner_id, f"rf_editor_class_{owner_id}_{entry[\'id\']}", entry.get("race_class_id"))')
        return node
    def visit_Call(self,node):
        self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=="update_checklist":
            node.keywords.append(ast.keyword(arg="race_class_id",value=ast.Name(id="rf_editor_class_id",ctx=ast.Load())))
            self.saves += 1
        return node


class _Filter(_PageVisitor):
    def __init__(self,second):
        self.second = second
        self.widgets = self.dictionaries = 0
    def visit_Assign(self,node):
        self.generic_visit(node)
        names = _names(node)
        value = "rf_second_class_id" if self.second else "rf_first_class_id"
        if "selected_race_name_id" in names:
            self.widgets += 1
            helper = "render_second_filter_selectbox" if self.second else "render_filter_selectbox"
            label = "Second Filter by Race Class" if self.second else "Filter by Race Class"
            return [node]+_stmts(f"{value} = {helper}({label!r}, owner_id, 'race_class_id', *_rf_class_options(owner_id))")
        if names.intersection({"selected_filters","second_selected_filters"}) and isinstance(node.value,ast.Dict):
            node.value.keys.append(ast.Constant("race_class_id"))
            node.value.values.append(ast.Name(id=value,ctx=ast.Load()))
            self.dictionaries += 1
        return node


def _write_class(fn,update=False):
    if any(a.arg=="race_class_id" for a in fn.args.args+fn.args.kwonlyargs):
        raise ValueError(f"{fn.name} already has a race-class argument.")
    fn.args.kwonlyargs.append(ast.arg(arg="race_class_id"))
    fn.args.kw_defaults.append(ast.Name(id="_RF_UNSET",ctx=ast.Load()))
    changed = 0
    for node in ast.walk(fn):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="execute" and len(node.args)>=2 and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and isinstance(node.args[1],ast.Tuple)):
            continue
        sql = node.args[0].value
        if update:
            if not re.search(r"UPDATE\s+checklists\s+SET",sql,re.I):
                continue
            where = re.search(r"\bWHERE\b",sql,re.I)
            tail = node.args[1].elts[-2:]
            if where is None or [n.id if isinstance(n,ast.Name) else None for n in tail]!=["checklist_id","owner_id"]:
                raise ValueError("Unexpected checklist UPDATE shape.")
            node.args[0].value = sql[:where.start()].rstrip()+", race_class_id=? "+sql[where.start():]
            node.args[1].elts.insert(len(node.args[1].elts)-2,ast.Name(id="race_class_id",ctx=ast.Load()))
        else:
            match = re.search(r"INSERT\s+INTO\s+checklists\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",sql,re.I|re.S)
            if not match:
                continue
            text = "INSERT INTO checklists ("+match.group(1).rstrip()+", race_class_id) VALUES ("+match.group(2).rstrip()+", ?)"
            node.args[0].value = sql[:match.start()]+text+sql[match.end():]
            node.args[1].elts.append(ast.Name(id="race_class_id",ctx=ast.Load()))
        changed += 1
    if changed!=1:
        raise ValueError(f"Expected one checklist write in {fn.name}; found {changed}.")
    position = 1 if fn.body and isinstance(fn.body[0],ast.Expr) and isinstance(fn.body[0].value,ast.Constant) and isinstance(fn.body[0].value.value,str) else 0
    fn.body[position:position] = _stmts("race_class_id = _rf_resolve_class(owner_id, "+("checklist_id" if update else "None")+", race_class_id)")


def patch_application(source):
    if MARKER in source:
        return source,{}
    if "# RACE_FEATURES_20261114_V1" in source:
        raise ValueError("An earlier feature update is already installed. Restore its source backup before applying this version.")
    tree, original = ast.parse(source), ast.parse(source)
    if any(isinstance(n,ast.FunctionDef) and n.name.startswith("_rf_") for n in tree.body):
        raise ValueError("Conflicting _rf_ helper names already exist.")
    names = ["init_db","add_checklist","update_checklist","get_user_checklists","get_filter_defaults","reset_filter_values","reset_second_filter_values","collect_current_filter_data","apply_saved_filter_to_session","build_summary_dataframe","render_race_checklist_page","render_race_reference_input","render_checklist_editor","render_checklist_review_page","render_second_filter_section","main"]
    functions = {name:_fn(tree,name) for name in names}
    _fn(tree,"_review_filter_restore_key")
    spans = {name:(_start(fn),fn.end_lineno) for name,fn in functions.items()}
    configs = [n for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=="st" and n.value.func.attr=="set_page_config"]
    if len(configs)!=1:
        raise ValueError("Expected one top-level page configuration.")
    config = configs[0]
    keyword = next((k for k in config.value.keywords if k.arg=="layout"),None)
    if keyword is None:
        config.value.keywords.append(ast.keyword(arg="layout",value=ast.Constant("wide")))
    else:
        keyword.value = ast.Constant("wide")
    functions["init_db"].body += _stmts("_rf_migrate()")
    _write_class(functions["add_checklist"])
    _write_class(functions["update_checklist"],True)
    functions["get_user_checklists"].decorator_list.insert(0,ast.Name(id="_rf_enrich",ctx=ast.Load()))
    _field(functions["get_filter_defaults"],{"race_name_id","odds_to"},"race_class_id","None")
    for name in ("reset_filter_values","reset_second_filter_values"):
        lists = [n.value for n in ast.walk(functions[name]) if isinstance(n,ast.Assign) and "selectbox_fields" in _names(n) and isinstance(n.value,ast.List)]
        if len(lists)!=1:
            raise ValueError(f"Cannot identify selector reset list in {name}.")
        lists[0].elts.append(ast.Constant("race_class_id"))
    _field(functions["collect_current_filter_data"],{"race_name_id","odds_to"},"race_class_id","get_value('race_class_id',None)")
    functions["apply_saved_filter_to_session"].body += _stmts("set_value('race_class_id', filter_data.get('race_class_id'))")
    _field(functions["build_summary_dataframe"],{"Horse","Jockey","Race"},"Race Class","entry.get('race_class_name') or ''")
    reg = functions["render_race_checklist_page"]
    visitor = _Registration()
    _body(reg,visitor)
    if set(visitor.keys)!=visitor.fields or visitor.saves!=1:
        raise ValueError("Registration integration failed. Missing fields: "+", ".join(sorted(visitor.fields-set(visitor.keys))))
    mapping = visitor.keys
    mapping["race_class_id"] = ast.parse("registration_key('race_class_id')",mode="eval").body
    positions = [i for i,n in enumerate(reg.body) if isinstance(n,ast.Assign) and "race_ids" in _names(n)]
    if len(positions)!=1:
        raise ValueError("Cannot locate registration race options.")
    reg.body.insert(positions[0]+1,ast.Expr(value=ast.Call(func=ast.Name(id="_rf_loader",ctx=ast.Load()),args=[ast.Name(id="owner_id",ctx=ast.Load()),ast.Constant("registration"),ast.Dict(keys=[ast.Constant(k) for k in mapping],values=[copy.deepcopy(v) for v in mapping.values()])],keywords=[])))
    # The helper returns a NAME STRING. Keep it intact and remove the
    # fallback selectbox's competing index default when a template set state.
    reference = functions["render_race_reference_input"]
    fallback_count = 0
    for node in ast.walk(reference):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="selectbox":
            for kw in node.keywords:
                if kw.arg=="index" and isinstance(kw.value,ast.Constant) and kw.value.value==0:
                    kw.value = ast.parse("None if key in st.session_state else 0",mode="eval").body
                    fallback_count += 1
    if fallback_count!=1:
        raise ValueError("Cannot identify the older-browser reference selector.")
    editor = _Editor()
    _body(functions["render_checklist_editor"],editor)
    if editor.widgets!=1 or editor.saves!=1:
        raise ValueError("Cannot integrate the checklist race-class editor.")
    for name,second in [("render_checklist_review_page",False),("render_second_filter_section",True)]:
        vf = _Filter(second)
        _body(functions[name],vf)
        if vf.widgets!=1 or vf.dictionaries!=1:
            raise ValueError(f"Cannot integrate race-class filtering in {name}.")
    review = functions["render_checklist_review_page"]
    headers = [i for i,n in enumerate(review.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=="header" and n.value.args and isinstance(n.value.args[0],ast.Constant) and n.value.args[0].value=="Checklist Review"]
    if len(headers)!=1:
        raise ValueError("Cannot locate the review header.")
    position = headers[0]+1
    if position<len(review.body) and isinstance(review.body[position],ast.Expr) and isinstance(review.body[position].value,ast.Call) and isinstance(review.body[position].value.func,ast.Name) and review.body[position].value.func.id=="_current_review_filter_place_panel":
        position += 1
    review.body[position:position] = _stmts("_rf_loader(owner_id,'review')")
    main = functions["main"]
    nav = [(i,n.value) for i,n in enumerate(main.body) if isinstance(n,ast.Assign) and "page" in _names(n) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=="radio"]
    if len(nav)!=1:
        raise ValueError("Cannot identify main navigation.")
    index,call = nav[0]
    options = call.args[1] if len(call.args)>1 else next((k.value for k in call.keywords if k.arg=="options"),None)
    if not isinstance(options,(ast.List,ast.Tuple)):
        raise ValueError("Navigation requires a literal options list.")
    for label in ("Race Templates","Race Classes","Race Blog"):
        if any(isinstance(n,ast.Constant) and n.value==label for n in options.elts):
            raise ValueError(f"Navigation already contains {label}.")
        options.elts.append(ast.Constant(label))
    # Insert after Logout handling, preserving logout on the new pages.
    insertion = index+1
    for i in range(index+1,len(main.body)):
        node = main.body[i]
        if isinstance(node,ast.If) and any(isinstance(c,ast.Constant) and c.value=="Logout" for c in ast.walk(node.test)):
            insertion = i+1
            break
    main.body[insertion:insertion] = _stmts("""
if page == 'Race Templates':
    _rf_templates_page(st.session_state.user_id)
    return
if page == 'Race Classes':
    _rf_classes_page(st.session_state.user_id)
    return
if page == 'Race Blog':
    _rf_blog_page(st.session_state.user_id)
    return
""")
    edits = []
    for name,fn in functions.items():
        ast.fix_missing_locations(fn)
        start,end = spans[name]
        edits.append((start,end,ast.unparse(fn)+"\n\n"))
    ast.fix_missing_locations(config)
    edits.append((config.lineno-1,config.end_lineno,ast.unparse(config)+"\n"))
    edits.sort(key=lambda x:x[0])
    if any(b[0]<a[1] for a,b in zip(edits,edits[1:])):
        raise ValueError("Overlapping edits detected.")
    lines = source.splitlines(keepends=True)
    for start,end,text in reversed(edits):
        lines[start:end] = [text]
    intermediate = "".join(lines)
    first = next(n for n in ast.parse(intermediate).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)))
    lines = intermediate.splitlines(keepends=True)
    lines.insert(_start(first),RUNTIME.strip("\n")+"\n\n")
    updated = "".join(lines)
    compile(updated,"<race-features-20261114>","exec")
    def normalize(t):
        body = []
        for n in t.body:
            if isinstance(n,ast.FunctionDef) and (n.name in functions or n.name.startswith("_rf_")):
                continue
            if isinstance(n,ast.Assign) and "_RF_UNSET" in _names(n):
                continue
            if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=="st" and n.value.func.attr=="set_page_config":
                continue
            body.append(n)
        return ast.dump(ast.Module(body=body,type_ignores=[]),include_attributes=False)
    if normalize(original)!=normalize(ast.parse(updated)):
        raise ValueError("Unexpected changes outside feature integration points.")
    if updated.count(MARKER)!=1:
        raise ValueError("Invalid feature patch marker.")
    return updated,{k:ast.unparse(v) for k,v in mapping.items()}


def _database_path(source,app,explicit):
    if explicit:
        return Path(explicit).resolve()
    paths = [n.value.value for n in ast.parse(source).body if isinstance(n,ast.Assign) and "DB_PATH" in _names(n) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)]
    if len(paths)!=1:
        raise ValueError("Cannot detect DB_PATH; specify --database PATH.")
    path = Path(paths[0])
    if path.is_absolute():
        return path.resolve()
    app_path,cwd_path = (app.parent/path).resolve(),path.resolve()
    if app_path!=cwd_path and app_path.exists() and cwd_path.exists():
        raise ValueError("Two possible databases exist; specify --database PATH.")
    return cwd_path if cwd_path.exists() else app_path


def _backup_database(path):
    if not path.exists():
        return None
    backup = path.with_name(path.name+".before-race-features-20261114-v2.bak")
    if backup.exists():
        raise FileExistsError(f"Database backup already exists: {backup}")
    original = destination = None
    try:
        original = sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10)
        destination = sqlite3.connect(backup)
        original.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise RuntimeError("Database backup integrity check failed.")
    except Exception:
        if destination is not None:
            destination.close()
            destination = None
        if backup.exists():
            backup.unlink()
        raise
    finally:
        if original is not None:
            original.close()
        if destination is not None:
            destination.close()
    return backup


def main():
    parser = argparse.ArgumentParser(description="Install race templates, classes, and private race blog features.")
    parser.add_argument("app_file",nargs="?",default="app.py")
    parser.add_argument("--database",help="Explicit database path to back up.")
    args = parser.parse_args()
    app = Path(args.app_file).resolve()
    if not app.is_file():
        raise SystemExit(f"Application file not found: {app}")
    source = app.read_text(encoding="utf-8-sig")
    if MARKER in source:
        print(f"Feature update already installed: {app}")
        return
    try:
        updated,mapping = patch_application(source)
        database = _database_path(source,app,args.database)
    except Exception as error:
        raise SystemExit(f"Validation failed. Application was not changed.\n{error}") from error
    backup = app.with_name(app.name+".before-race-features-20261114-v2.bak")
    if backup.exists():
        raise SystemExit(f"Source backup already exists: {backup}\nMove or rename it before retrying.")
    try:
        database_backup = _backup_database(database)
        shutil.copy2(app,backup)
    except Exception as error:
        raise SystemExit(f"Backup failed. Application source was not changed.\n{error}") from error
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",dir=app.parent,prefix=f".{app.name}.",suffix=".tmp",delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
        shutil.copymode(app,temporary)
        temporary.replace(app)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print(f"Database path: {database}")
    print(f"Database backup: {database_backup or 'No existing database at detected path'}")
    print("Syntax and AST-scope validation passed.")
    print("Registration race selector: name string via render_race_reference_input.")
    for field,key in mapping.items():
        print(f"  {field}: {key}")
    print("Restart the app. Migration runs on first startup.")
    print("Added Race Templates, Race Classes, and Race Blog navigation.")
    print("Application default layout is wide.")
    print("Test template loading on both checklist pages and class selection/filtering.")
    print("Test blog/tag search and image upload/display.")
    print("CSV formats are unchanged; legacy updates preserve race class.")
    print("Back up the entire database: saved-filter JSON excludes blog/template data.")
    print("Interactive browser testing remains required.")


if __name__ == "__main__":
    main()

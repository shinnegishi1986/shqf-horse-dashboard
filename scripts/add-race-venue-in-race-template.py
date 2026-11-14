# scripts/add-race-venue-in-race-template.py
# Apply after the corrected race-feature updater (20261114 V2).
# Stop Streamlit first.
# python scripts/add-race-venue-in-race-template.py app.py
# Optional: --database data/horse_checklist_app.db
# Database migration runs on the next application startup.

RUNTIME=r'''
# RACE_TEMPLATE_VENUE_AND_EDITOR_LOAD_V1

def _rf_venue_migrate():
    conn = _rf_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if "venue_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(rf_race_templates)")}:
                conn.execute("ALTER TABLE rf_race_templates ADD COLUMN venue_id INTEGER REFERENCES venues(id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rf_template_venue ON rf_race_templates(owner_id,venue_id)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _rf_venue_options(owner_id):
    rows = get_user_venues(owner_id)
    return [None]+[r["id"] for r in rows], {r["id"]:r["venue_name"] for r in rows}


def _rf_template_venue_input(owner_id):
    ids, labels = _rf_venue_options(owner_id)
    if not labels:
        st.info("Register a venue from the Venues menu before saving a template.")
    return st.selectbox("Venue — required when saving a template",ids,
        format_func=lambda value:"(Select a venue)" if value is None else labels[value],
        key=f"rf_template_venue_{owner_id}")


def _rf_templates(owner_id):
    return _rf_rows("""SELECT t.*,rn.race_name,rc.race_class_name,v.venue_name
        FROM rf_race_templates t
        LEFT JOIN race_names rn ON rn.id=t.race_name_id AND rn.owner_id=t.owner_id
        LEFT JOIN race_classes rc ON rc.id=t.race_class_id AND rc.owner_id=t.owner_id
        LEFT JOIN venues v ON v.id=t.venue_id AND v.owner_id=t.owner_id
        WHERE t.owner_id=? ORDER BY t.race_date DESC,t.program_number,t.id DESC""",(owner_id,))


def _rf_label(row):
    return (f"{row['race_date']} | {row.get('venue_name') or '(Venue not set)'} | "
        f"R{row['program_number']} | {row.get('race_name') or '(Race name unavailable)'} | "
        f"{row['distance']}m | {row['number_of_horses']} horses"
        +(f" | {row['race_class_name']}" if row.get("race_class_name") else ""))


def _rf_template(owner_id,template_id):
    row=next((r for r in _rf_templates(owner_id) if r["id"]==template_id),None)
    if row is None or not row.get("race_name"):
        raise ValueError("The race template or its race name is unavailable.")
    _rf_resolve_class(owner_id,None,row["race_class_id"])
    if row.get("venue_id") is not None and not row.get("venue_name"):
        raise ValueError("The template's venue is unavailable. Choose a valid venue and save the template again.")
    return row


def _rf_save_template(owner_id,name_id,new_name,race_date,program,distance,horses,class_id,*,venue_id=None):
    if venue_id is None:
        raise ValueError("Select a venue before saving the race template.")
    if not 1<=int(program)<=12 or not 1<=int(distance)<=5000 or not 1<=int(horses)<=18:
        raise ValueError("Race template numbers are outside the supported ranges.")
    if not date(1980,1,1)<=race_date<=date(2100,12,31):
        raise ValueError("Race date must be between 1980 and 2100.")
    conn=_rf_db()
    try:
        with conn:
            if not conn.execute("SELECT 1 FROM venues WHERE owner_id=? AND id=?",(owner_id,venue_id)).fetchone():
                raise ValueError("The selected venue does not belong to this account.")
            if class_id is not None and not conn.execute("SELECT 1 FROM race_classes WHERE owner_id=? AND id=?",(owner_id,class_id)).fetchone():
                raise ValueError("The selected class does not belong to this account.")
            if name_id is None:
                name=new_name.strip()
                if not name or len(name)>200:
                    raise ValueError("Enter a race name of 1–200 characters.")
                found=conn.execute("SELECT id FROM race_names WHERE owner_id=? AND RF_CASEFOLD(race_name)=RF_CASEFOLD(?)",(owner_id,name)).fetchone()
                name_id=found["id"] if found else conn.execute("INSERT INTO race_names(owner_id,race_name) VALUES (?,?)",(owner_id,name)).lastrowid
            elif not conn.execute("SELECT 1 FROM race_names WHERE owner_id=? AND id=?",(owner_id,name_id)).fetchone():
                raise ValueError("Race name does not belong to this account.")
            conn.execute("""INSERT INTO rf_race_templates
                (owner_id,race_name_id,race_date,program_number,distance,number_of_horses,race_class_id,venue_id)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(owner_id,race_name_id,race_date,program_number) DO UPDATE SET
                distance=excluded.distance,number_of_horses=excluded.number_of_horses,
                race_class_id=excluded.race_class_id,venue_id=excluded.venue_id""",
                (owner_id,name_id,race_date.isoformat(),int(program),int(distance),int(horses),class_id,venue_id))
    finally:
        conn.close()


def _rf_load(owner_id,template_id,mode,target_keys=None):
    try:
        row=_rf_template(owner_id,template_id)
        if mode=="registration":
            values={"selected_race_idx":row["race_name"],"date_of_race":date.fromisoformat(row["race_date"]),
                "program_number":row["program_number"],"distance":row["distance"],
                "number_of_horses":row["number_of_horses"],"race_class_id":row["race_class_id"]}
            if row.get("venue_id") is not None:
                values["selected_venue_idx"]=row["venue_name"]
            if not target_keys or any(field not in target_keys for field in values):
                raise ValueError("Registration widget mapping is incomplete.")
            for field,value in values.items():
                st.session_state[target_keys[field]]=value
            for field in ("selected_race_idx","selected_venue_idx"):
                if field in values:
                    st.session_state[target_keys[field]+"_new_name"]=""
        else:
            reset_filter_values(owner_id)
            values={"race_name_id":row["race_name_id"],"race_class_id":row["race_class_id"],
                "venue_ids":[row["venue_id"]] if row.get("venue_id") is not None else [],
                "date_from":date.fromisoformat(row["race_date"]),"date_to":date.fromisoformat(row["race_date"]),
                "program_number":row["program_number"],"number_of_horses":row["number_of_horses"],
                "distance_from":row["distance"],"distance_to":row["distance"],"enable_distance_filter":True,
                "page_number":1,"active_filter_title":"Race template: "+_rf_label(row)}
            for field,value in values.items():
                st.session_state[saved_filter_key(owner_id,field)]=value
            st.session_state[filter_load_version_key(owner_id)]+=1
            st.session_state[second_filter_key(owner_id,"enabled")]=False
            st.session_state.pop(_review_filter_restore_key(owner_id),None)
            st.session_state.pop("selected_review_checklist_id",None)
        notice="Loaded: "+_rf_label(row)
        if row.get("venue_id") is None:
            notice+=". This older template has no venue. Re-save it with a venue; registration venue was not changed and Review has no venue restriction."
        st.session_state[f"rf_notice_{mode}_{owner_id}"]=notice
    except (ValueError,sqlite3.Error) as error:
        st.session_state[f"rf_error_{mode}_{owner_id}"]=str(error)


def _rf_venue_editor_key(owner_id,entry_id,field):
    return f"rf_venue_editor_{owner_id}_{entry_id}_{field}"


def _rf_venue_editor_widget(widget_function,*args,**kwargs):
    key=kwargs.get("key")
    if key is not None and key in st.session_state:
        if getattr(widget_function,"__name__","")=="selectbox":
            kwargs["index"]=None
        else:
            kwargs["value"]=None
    return widget_function(*args,**kwargs)


def _rf_venue_load_editor(owner_id,entry_id,template_id):
    try:
        if not _rf_rows("SELECT id FROM checklists WHERE owner_id=? AND id=?",(owner_id,entry_id)):
            raise ValueError("Checklist is unavailable.")
        row=_rf_template(owner_id,template_id)
        race_ids=[None]+[r["id"] for r in get_user_race_names(owner_id)]
        venue_ids=[None]+[r["id"] for r in get_user_venues(owner_id)]
        values={"edit_race_idx":race_ids.index(row["race_name_id"]),
            "edit_distance":row["distance"],"edit_date":date.fromisoformat(row["race_date"]),
            "edit_program_number":row["program_number"],"edit_number_of_horses":row["number_of_horses"]}
        if row.get("venue_id") is not None:
            values["edit_venue_idx"]=venue_ids.index(row["venue_id"])
        for field,value in values.items():
            st.session_state[_rf_venue_editor_key(owner_id,entry_id,field)]=value
        st.session_state[f"rf_editor_class_{owner_id}_{entry_id}"]=row["race_class_id"]
        message="Loaded into editor: "+_rf_label(row)+". Click Update Checklist to save."
        if row.get("venue_id") is None:
            message+=" The existing venue was left unchanged."
        st.session_state[f"rf_venue_editor_notice_{owner_id}_{entry_id}"]=message
    except (ValueError,sqlite3.Error) as error:
        st.session_state[f"rf_venue_editor_error_{owner_id}_{entry_id}"]=str(error)


def _rf_venue_editor_loader(owner_id,entry):
    entry_id=entry["id"]
    notice=st.session_state.pop(f"rf_venue_editor_notice_{owner_id}_{entry_id}",None)
    error=st.session_state.pop(f"rf_venue_editor_error_{owner_id}_{entry_id}",None)
    if notice:
        st.success(notice)
    if error:
        st.error(error)
    with st.expander("Load Race Template into This Checklist",expanded=False):
        rows=_rf_templates(owner_id)
        if not rows:
            st.info("Create a race template first.")
            return
        lookup={r["id"]:r for r in rows}
        selected=st.selectbox("Race template for this checklist",[None]+list(lookup),
            format_func=lambda value:"(Select a template)" if value is None else _rf_label(lookup[value]),
            key=f"rf_venue_editor_template_{owner_id}_{entry_id}")
        st.caption("Loads race name, venue, date, program number, distance, number of horses, and class. It does not change Review filters or save the record until you click Update Checklist.")
        st.button("Load into Checklist Editor",key=f"rf_venue_editor_load_{owner_id}_{entry_id}",
            disabled=selected is None,on_click=_rf_venue_load_editor,args=(owner_id,entry_id,selected))


def _rf_venue_set_existing(owner_id,template_id,venue_id):
    if venue_id is None:
        raise ValueError("Select a venue.")
    conn=_rf_db()
    try:
        with conn:
            if not conn.execute("SELECT 1 FROM venues WHERE owner_id=? AND id=?",(owner_id,venue_id)).fetchone():
                raise ValueError("The selected venue does not belong to this account.")
            cursor=conn.execute("UPDATE rf_race_templates SET venue_id=? WHERE owner_id=? AND id=?",(venue_id,owner_id,template_id))
            if cursor.rowcount!=1:
                raise ValueError("Race template is unavailable.")
    finally:
        conn.close()


def _rf_venue_existing_editor(owner_id):
    with st.expander("Set Venue on an Existing Template",expanded=False):
        rows=_rf_templates(owner_id)
        ids,labels=_rf_venue_options(owner_id)
        if not rows or len(ids)==1:
            st.info("Register a race template and at least one venue first.")
            return
        lookup={r["id"]:r for r in rows}
        selected=st.selectbox("Existing race template",list(lookup),
            format_func=lambda value:_rf_label(lookup[value]),key=f"rf_venue_existing_{owner_id}")
        row=lookup[selected]
        current=row.get("venue_id") if row.get("venue_id") in ids else None
        key=f"rf_venue_existing_choice_{owner_id}_{selected}"
        venue=st.selectbox("Venue for this template",ids,
            index=None if key in st.session_state else ids.index(current),
            format_func=lambda value:"(Select a venue)" if value is None else labels[value],key=key)
        st.caption("Updates only this template's venue. Its ID, other settings, blog links, and existing checklists are unchanged.")
        if st.button("Save Template Venue",key=f"rf_venue_existing_save_{owner_id}",disabled=venue is None):
            try:
                _rf_venue_set_existing(owner_id,selected,venue)
                st.success("Template venue saved. Other template settings were preserved.")
            except (ValueError,sqlite3.Error) as error:
                st.error(str(error))
'''


import argparse
import ast
import copy
from pathlib import Path
import shutil
import sqlite3
import tempfile

MARKER="# RACE_TEMPLATE_VENUE_AND_EDITOR_LOAD_V1"


def _fn(tree,name):
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matches)!=1:
        raise ValueError(f"Expected one {name}; found {len(matches)}.")
    return matches[0]


def _names(node):
    return {n.id for target in node.targets for n in ast.walk(target) if isinstance(n,ast.Name)} if isinstance(node,ast.Assign) else set()


def _start(node):
    return min([node.lineno]+[d.lineno for d in node.decorator_list])-1


def _stmts(code):
    return ast.parse(code).body


class _Page(ast.NodeTransformer):
    def visit_FunctionDef(self,node):
        return node
    def visit_AsyncFunctionDef(self,node):
        return node


def _body(fn,visitor):
    output=[]
    for node in fn.body:
        result=visitor.visit(node)
        if result is not None:
            output.extend(result if isinstance(result,list) else [result])
    fn.body=output


class _TemplatePage(_Page):
    def __init__(self):
        self.selectors=self.saves=self.tables=0
    def visit_Assign(self,node):
        self.generic_visit(node)
        if "class_id" in _names(node):
            self.selectors+=1
            return [node]+_stmts("rf_template_venue_id = _rf_template_venue_input(owner_id)")
        return node
    def visit_Call(self,node):
        self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=="_rf_save_template":
            if any(k.arg=="venue_id" for k in node.keywords):
                raise ValueError("The template save call already includes venue_id.")
            node.keywords.append(ast.keyword(arg="venue_id",value=ast.Name(id="rf_template_venue_id",ctx=ast.Load())))
            self.saves+=1
        return node
    def visit_Dict(self,node):
        self.generic_visit(node)
        keys={k.value for k in node.keys if isinstance(k,ast.Constant)}
        if {"ID","Date","Race","Program","Distance"}.issubset(keys):
            node.keys.append(ast.Constant("Venue"))
            node.values.append(ast.parse("r.get('venue_name') or '(Not set)'",mode="eval").body)
            self.tables+=1
        return node


class _EditorWidgets(_Page):
    fields={"edit_race_idx","edit_venue_idx","edit_distance","edit_date","edit_program_number","edit_number_of_horses"}
    def __init__(self):
        self.found=set()
    def visit_Assign(self,node):
        field=self.fields.intersection(_names(node))
        if not field:
            return self.generic_visit(node)
        if len(field)!=1:
            raise ValueError("Ambiguous checklist editor assignment.")
        name=next(iter(field))
        if name in self.found:
            raise ValueError(f"Multiple editor widgets found for {name}.")
        call=node.value
        kind="selectbox" if name.endswith("_idx") else "date_input" if name=="edit_date" else "number_input"
        if not (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=="st" and call.func.attr==kind):
            raise ValueError(f"Unsupported editor widget for {name}.")
        if any(k.arg=="key" for k in call.keywords):
            raise ValueError(f"Editor field {name} already has a key; a source-specific adjustment is required.")
        if len(call.args)>(2 if kind=="selectbox" else 1):
            raise ValueError(f"Unexpected positional defaults for {name}.")
        key=ast.parse(f"_rf_venue_editor_key(owner_id,entry['id'],{name!r})",mode="eval").body
        node.value=ast.Call(func=ast.Name(id="_rf_venue_editor_widget",ctx=ast.Load()),args=[call.func,*call.args],keywords=[*call.keywords,ast.keyword(arg="key",value=key)])
        self.found.add(name)
        return node


def patch_application(source):
    if MARKER in source:
        return source
    if "# RACE_FEATURES_20261114_V2" not in source:
        raise ValueError("Install the corrected race-feature updater (20261114 V2) first.")
    tree=ast.parse(source)
    originals=ast.parse(source)
    replacement_names={"_rf_templates","_rf_label","_rf_template","_rf_save_template","_rf_load"}
    edit_names={"init_db","_rf_templates_page","render_race_checklist_page","render_checklist_editor"}
    functions={name:_fn(tree,name) for name in replacement_names|edit_names}
    _fn(tree,"_rf_db")
    _fn(tree,"_rf_rows")
    _fn(tree,"_rf_migrate")
    runtime_names={n.name for n in ast.parse(RUNTIME).body if isinstance(n,ast.FunctionDef)}
    for name in runtime_names-replacement_names:
        if any(isinstance(n,ast.FunctionDef) and n.name==name for n in tree.body):
            raise ValueError(f"Conflicting helper already exists: {name}")
    spans={name:(_start(fn),fn.end_lineno) for name,fn in functions.items()}
    functions["init_db"].body+=_stmts("_rf_venue_migrate()")
    page=functions["_rf_templates_page"]
    visitor=_TemplatePage()
    _body(page,visitor)
    if (visitor.selectors,visitor.saves,visitor.tables)!=(1,1,1):
        raise ValueError("Cannot safely identify the template form/save/table integration points.")
    page.body+=_stmts("_rf_venue_existing_editor(owner_id)")
    # Recover the exact name-input key used by the registration venue field.
    reg=functions["render_race_checklist_page"]
    venue_assignments=[n for n in ast.walk(reg) if isinstance(n,ast.Assign) and "selected_venue_idx" in _names(n)]
    if len(venue_assignments)!=1:
        raise ValueError("Cannot uniquely identify the registration venue selector.")
    venue_call=venue_assignments[0].value
    if not (isinstance(venue_call,ast.Call) and isinstance(venue_call.func,ast.Name) and venue_call.func.id=="render_race_reference_input"):
        raise ValueError("Expected the existing name-based registration venue helper.")
    venue_key=next((k.value for k in venue_call.keywords if k.arg=="key"),None)
    if venue_key is None:
        raise ValueError("The registration venue widget has no explicit key.")
    loaders=[n for n in ast.walk(reg) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_rf_loader" and len(n.args)>=3 and isinstance(n.args[1],ast.Constant) and n.args[1].value=="registration"]
    if len(loaders)!=1 or not isinstance(loaders[0].args[2],ast.Dict):
        raise ValueError("Cannot identify the registration template-loader key mapping.")
    mapping=loaders[0].args[2]
    if any(isinstance(k,ast.Constant) and k.value=="selected_venue_idx" for k in mapping.keys):
        raise ValueError("The registration template loader already maps a venue.")
    mapping.keys.append(ast.Constant("selected_venue_idx"))
    mapping.values.append(copy.deepcopy(venue_key))
    editor=functions["render_checklist_editor"]
    widget_visitor=_EditorWidgets()
    _body(editor,widget_visitor)
    if widget_visitor.found!=widget_visitor.fields:
        raise ValueError("Missing editor fields: "+", ".join(sorted(widget_visitor.fields-widget_visitor.found)))
    forms=[i for i,n in enumerate(editor.body) if isinstance(n,ast.With) and any(isinstance(item.context_expr,ast.Call) and isinstance(item.context_expr.func,ast.Attribute) and item.context_expr.func.attr=="form" for item in n.items)]
    if len(forms)!=1:
        raise ValueError("Cannot uniquely identify the checklist editor form.")
    editor.body[forms[0]:forms[0]]=_stmts("_rf_venue_editor_loader(owner_id,entry)")
    edits=[]
    for name,fn in functions.items():
        start,end=spans[name]
        if name in replacement_names:
            if fn.decorator_list:
                raise ValueError(f"Unexpected decorators on {name}.")
            text=""
        else:
            ast.fix_missing_locations(fn)
            text=ast.unparse(fn)+"\n\n"
        edits.append((start,end,text))
    edits.sort(key=lambda x:x[0])
    if any(b[0]<a[1] for a,b in zip(edits,edits[1:])):
        raise ValueError("Overlapping source edits detected.")
    lines=source.splitlines(keepends=True)
    for start,end,text in reversed(edits):
        lines[start:end]=[text]
    intermediate="".join(lines)
    first=next(n for n in ast.parse(intermediate).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)))
    lines=intermediate.splitlines(keepends=True)
    lines.insert(_start(first),RUNTIME.strip("\n")+"\n\n")
    updated="".join(lines)
    compile(updated,"<race-template-venue>","exec")
    allowed=runtime_names|edit_names
    def normalize(t):
        return ast.dump(ast.Module(body=[n for n in t.body if not(isinstance(n,ast.FunctionDef) and n.name in allowed)],type_ignores=[]),include_attributes=False)
    if normalize(originals)!=normalize(ast.parse(updated)):
        raise ValueError("Unexpected changes outside venue/template integration points.")
    if updated.count(MARKER)!=1:
        raise ValueError("Invalid venue patch marker.")
    return updated


def _database_path(source,app,explicit):
    if explicit:
        return Path(explicit).resolve()
    values=[n.value.value for n in ast.parse(source).body if isinstance(n,ast.Assign) and "DB_PATH" in _names(n) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)]
    if len(values)!=1:
        raise ValueError("Cannot detect DB_PATH; specify --database PATH.")
    path=Path(values[0])
    if path.is_absolute():
        return path.resolve()
    a,b=(app.parent/path).resolve(),path.resolve()
    if a!=b and a.exists() and b.exists():
        raise ValueError("Two possible databases exist; specify --database PATH.")
    return b if b.exists() else a


def _backup_database(path):
    if not path.exists():
        return None
    backup=path.with_name(path.name+".before-template-venue.bak")
    if backup.exists():
        raise FileExistsError(f"Database backup already exists: {backup}")
    source=destination=None
    try:
        source=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10)
        destination=sqlite3.connect(backup)
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise RuntimeError("Database backup integrity check failed.")
    except Exception:
        if destination is not None:
            destination.close()
            destination=None
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
    parser=argparse.ArgumentParser(description="Add venue to race templates and load template settings into checklist editors.")
    parser.add_argument("app_file",nargs="?",default="app.py")
    parser.add_argument("--database",help="Explicit database path to back up.")
    args=parser.parse_args()
    app=Path(args.app_file).resolve()
    if not app.is_file():
        raise SystemExit(f"Application file not found: {app}")
    source=app.read_text(encoding="utf-8-sig")
    if MARKER in source:
        print(f"The template-venue update is already installed: {app}")
        return
    try:
        updated=patch_application(source)
        database=_database_path(source,app,args.database)
    except Exception as error:
        raise SystemExit(f"Validation failed. Application was not changed.\n{error}") from error
    backup=app.with_name(app.name+".before-template-venue.bak")
    if backup.exists():
        raise SystemExit(f"Source backup already exists: {backup}\nMove or rename it before retrying.")
    try:
        database_backup=_backup_database(database)
        shutil.copy2(app,backup)
    except Exception as error:
        raise SystemExit(f"Backup failed. Application source was not changed.\n{error}") from error
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",dir=app.parent,prefix=f".{app.name}.",suffix=".tmp",delete=False) as handle:
            temporary=Path(handle.name)
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
    print("Restart the app: the venue column migration runs on startup.")
    print("Templates retain their IDs and existing blog associations.")
    print("New/re-saved templates require a venue.")
    print("Use Set Venue on an Existing Template to update only its venue.")
    print("Templates load venue into registration, Review filters, and the checklist editor.")
    print("Editor template loading does not save until Update Checklist is clicked.")
    print("Existing checklist rows are not changed by the migration.")
    print("Template identity remains race name + date + program number; saving that combination updates its venue.")
    print("Interactive browser testing remains required.")


if __name__=="__main__":
    main()

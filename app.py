import streamlit as st
import sqlite3
import os
import bcrypt
import json
from datetime import date

DB_PATH = 'data/horse_checklist_app.db'

# --- Database Setup ---
def init_db():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_id INTEGER,
            jockey_id INTEGER,
            trainer_id INTEGER,
            date_of_race TEXT,
            memo TEXT,
            finished_place TEXT,
            checklist TEXT,
            FOREIGN KEY(owner_id) REFERENCES users(id),
            FOREIGN KEY(horse_id) REFERENCES horses(id),
            FOREIGN KEY(jockey_id) REFERENCES jockeys(id),
            FOREIGN KEY(trainer_id) REFERENCES trainers(id)
        )
    ''')
    cursor.execute("PRAGMA table_info(checklists)")
    columns = [row[1] for row in cursor.fetchall()]
    if "jockey_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN jockey_id INTEGER")
    if "trainer_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN trainer_id INTEGER")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invitation_codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS horses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_name TEXT NOT NULL,
            UNIQUE(owner_id, horse_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jockeys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            jockey_name TEXT NOT NULL,
            UNIQUE(owner_id, jockey_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trainers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            trainer_name TEXT NOT NULL,
            UNIQUE(owner_id, trainer_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            criteria_name TEXT NOT NULL,
            UNIQUE(owner_id, criteria_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')

    cursor.execute("PRAGMA table_info(checklists)")
    columns = [row[1] for row in cursor.fetchall()]
    if "date_of_race" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN date_of_race TEXT')
    if "memo" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN memo TEXT')
    if "finished_place" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN finished_place TEXT')
    if "checklist" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN checklist TEXT')

    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- User Functions ---
def register_user(username, display_name, password, invitation_code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return False, "Username already exists."
    cursor.execute("SELECT used FROM invitation_codes WHERE code = ?", (invitation_code,))
    code_row = cursor.fetchone()
    if not code_row:
        conn.close()
        return False, "Invalid invitation code."
    if code_row['used']:
        conn.close()
        return False, "Invitation code has already been used."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cursor.execute("INSERT INTO users (username, display_name, password) VALUES (?, ?, ?)",
                   (username, display_name, hashed))
    cursor.execute("UPDATE invitation_codes SET used = 1 WHERE code = ?", (invitation_code,))
    conn.commit()
    conn.close()
    return True, "Registration successful!"

def login_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
        return True, user['display_name'], user['id']
    return False, None, None

def add_invitation_code(code):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO invitation_codes (code, used) VALUES (?, 0)", (code,))
        conn.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False
    conn.close()
    return result

# --- Horse Functions ---
def add_horse(owner_id, horse_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM horses WHERE owner_id = ? AND horse_name = ?", (owner_id, horse_name))
    if cursor.fetchone():
        conn.close()
        return False, "Horse already registered."
    cursor.execute("INSERT INTO horses (owner_id, horse_name) VALUES (?, ?)", (owner_id, horse_name))
    conn.commit()
    conn.close()
    return True, "Horse registered!"

def get_user_horses(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, horse_name FROM horses WHERE owner_id = ?", (owner_id,))
    horses = [{"id": row["id"], "horse_name": row["horse_name"]} for row in cursor.fetchall()]
    conn.close()
    return horses

# --- Jockey Functions ---
def add_jockey(owner_id, jockey_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jockeys WHERE owner_id = ? AND jockey_name = ?", (owner_id, jockey_name))
    if cursor.fetchone():
        conn.close()
        return False, "Jockey already registered."
    cursor.execute("INSERT INTO jockeys (owner_id, jockey_name) VALUES (?, ?)", (owner_id, jockey_name))
    conn.commit()
    conn.close()
    return True, "Jockey registered!"

def get_user_jockeys(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, jockey_name FROM jockeys WHERE owner_id = ?", (owner_id,))
    jockeys = [{"id": row["id"], "jockey_name": row["jockey_name"]} for row in cursor.fetchall()]
    conn.close()
    return jockeys

# --- Trainer Functions ---
def add_trainer(owner_id, trainer_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM trainers WHERE owner_id = ? AND trainer_name = ?", (owner_id, trainer_name))
    if cursor.fetchone():
        conn.close()
        return False, "Trainer already registered."
    cursor.execute("INSERT INTO trainers (owner_id, trainer_name) VALUES (?, ?)", (owner_id, trainer_name))
    conn.commit()
    conn.close()
    return True, "Trainer registered!"

def get_user_trainers(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, trainer_name FROM trainers WHERE owner_id = ?", (owner_id,))
    trainers = [{"id": row["id"], "trainer_name": row["trainer_name"]} for row in cursor.fetchall()]
    conn.close()
    return trainers

# --- Criteria Functions ---
def add_criteria(owner_id, criteria_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM criteria WHERE owner_id = ? AND criteria_name = ?", (owner_id, criteria_name))
    if cursor.fetchone():
        conn.close()
        return False, "Criteria already exists."
    cursor.execute("INSERT INTO criteria (owner_id, criteria_name) VALUES (?, ?)", (owner_id, criteria_name))
    conn.commit()
    conn.close()
    return True, "Criteria added!"

def get_user_criteria(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, criteria_name FROM criteria WHERE owner_id = ?", (owner_id,))
    criteria = [{"id": row["id"], "criteria_name": row["criteria_name"]} for row in cursor.fetchall()]
    conn.close()
    return criteria

# --- Checklist Functions ---
def add_checklist(owner_id, horse_id, jockey_id, trainer_id, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    cursor.execute(
        "INSERT INTO checklists (owner_id, horse_id, jockey_id, trainer_id, date_of_race, memo, finished_place, checklist) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (owner_id, horse_id, jockey_id, trainer_id, date_of_race, memo, finished_place, checklist_json)
    )
    conn.commit()
    conn.close()
    return True, "Checklist saved!"

def update_checklist(checklist_id, owner_id, horse_id, jockey_id, trainer_id, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    cursor.execute(
        "UPDATE checklists SET horse_id=?, jockey_id=?, trainer_id=?, date_of_race=?, memo=?, finished_place=?, checklist=? WHERE id=? AND owner_id=?",
        (horse_id, jockey_id, trainer_id, date_of_race, memo, finished_place, checklist_json, checklist_id, owner_id)
    )
    conn.commit()
    conn.close()
    return True, "Checklist updated!"

def get_user_checklists(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT checklists.id, horses.id as horse_id, horses.horse_name, jockeys.id as jockey_id, jockeys.jockey_name,
               trainers.id as trainer_id, trainers.trainer_name,
               checklists.date_of_race, checklists.memo, checklists.finished_place, checklists.checklist
        FROM checklists
        LEFT JOIN horses ON checklists.horse_id = horses.id
        LEFT JOIN jockeys ON checklists.jockey_id = jockeys.id
        LEFT JOIN trainers ON checklists.trainer_id = trainers.id
        WHERE checklists.owner_id = ?
        ORDER BY checklists.date_of_race DESC, checklists.id DESC
    """, (owner_id,))
    results = cursor.fetchall()
    conn.close()
    checklists = []
    for row in results:
        checklist_data = json.loads(row['checklist']) if row['checklist'] else {}
        checklists.append({
            "id": row['id'],
            "horse_id": row['horse_id'],
            "horse_name": row['horse_name'] if row['horse_name'] else "(No horse selected)",
            "jockey_id": row['jockey_id'],
            "jockey_name": row['jockey_name'] if row['jockey_name'] else "(No jockey selected)",
            "trainer_id": row['trainer_id'],
            "trainer_name": row['trainer_name'] if row['trainer_name'] else "(No trainer selected)",
            "date_of_race": row['date_of_race'],
            "memo": row['memo'] if row['memo'] else "",
            "finished_place": row['finished_place'] if row['finished_place'] else "",
            "checklist": checklist_data
        })
    return checklists

# --- Streamlit App ---
init_db()
st.set_page_config(page_title="Horse Checklist App", layout="centered")
st.title("🐎 Horse Checklist App")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.display_name = ""
    st.session_state.user_id = None

if st.session_state.logged_in:
    st.sidebar.write(f"Logged in as: {st.session_state.display_name}")
    page = st.sidebar.radio("Menu", [
        "Register Horse (Template)",
        "Register Jockey (Template)",
        "Register Trainer (Template)",
        "Register Criteria (Template)",
        "Race Checklist",
        "Checklist Review"
    ])

    if st.sidebar.button("Logout", key="logout_btn"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.display_name = ""
        st.session_state.user_id = None
        st.rerun()

    if page == "Register Horse (Template)":
        st.header("Register a Horse Template")
        horse_name = st.text_input("Horse Name", key="horse_name_input")
        add_horse_clicked = st.button("Add Horse", key="add_horse_btn")
        if add_horse_clicked:
            if not horse_name.strip():
                st.error("Please enter a horse name.")
            else:
                success, msg = add_horse(st.session_state.user_id, horse_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    elif page == "Register Jockey (Template)":
        st.header("Register a Jockey Template")
        jockey_name = st.text_input("Jockey Name", key="jockey_name_input")
        add_jockey_clicked = st.button("Add Jockey", key="add_jockey_btn")
        if add_jockey_clicked:
            if not jockey_name.strip():
                st.error("Please enter a jockey name.")
            else:
                success, msg = add_jockey(st.session_state.user_id, jockey_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    elif page == "Register Trainer (Template)":
        st.header("Register a Trainer Template")
        trainer_name = st.text_input("Trainer Name", key="trainer_name_input")
        add_trainer_clicked = st.button("Add Trainer", key="add_trainer_btn")
        if add_trainer_clicked:
            if not trainer_name.strip():
                st.error("Please enter a trainer name.")
            else:
                success, msg = add_trainer(st.session_state.user_id, trainer_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    elif page == "Register Criteria (Template)":
        st.header("Register Checklist Criteria Template")
        criteria_name = st.text_input("Criteria Name (e.g., Won Previous Race)", key="criteria_name_input")
        add_criteria_clicked = st.button("Add Criteria", key="add_criteria_btn")
        if add_criteria_clicked:
            if not criteria_name.strip():
                st.error("Please enter a criteria name.")
            else:
                success, msg = add_criteria(st.session_state.user_id, criteria_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    elif page == "Race Checklist":
        st.header("Race Checklist")
        horses = get_user_horses(st.session_state.user_id)
        jockeys = get_user_jockeys(st.session_state.user_id)
        trainers = get_user_trainers(st.session_state.user_id)
        criteria = get_user_criteria(st.session_state.user_id)
        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]
        jockey_options = ["(No jockey selected)"] + [j["jockey_name"] for j in jockeys]
        jockey_ids = [None] + [j["id"] for j in jockeys]
        trainer_options = ["(No trainer selected)"] + [t["trainer_name"] for t in trainers]
        trainer_ids = [None] + [t["id"] for t in trainers]

        selected_horse_idx = st.selectbox("Select Horse (optional)", range(len(horse_options)), format_func=lambda x: horse_options[x], key="race_horse_select")
        selected_jockey_idx = st.selectbox("Select Jockey (optional)", range(len(jockey_options)), format_func=lambda x: jockey_options[x], key="race_jockey_select")
        selected_trainer_idx = st.selectbox("Select Trainer (optional)", range(len(trainer_options)), format_func=lambda x: trainer_options[x], key="race_trainer_select")
        date_of_race = st.date_input("Date of Race", value=date.today(), key="race_date_input")
        memo = st.text_area("Memo (optional)", key="race_memo_input")
        finished_place = st.text_input("Finished Place (optional)", key="race_finished_place_input")
        checklist_data = {}
        st.write("Check the criteria that apply for this race (optional):")
        for c in criteria:
            checklist_data[c["criteria_name"]] = st.checkbox(c["criteria_name"], key=f"check_{c['id']}")
        save_checklist_clicked = st.button("Save Checklist", key="save_checklist_btn")
        if save_checklist_clicked:
            horse_id = horse_ids[selected_horse_idx]
            jockey_id = jockey_ids[selected_jockey_idx]
            trainer_id = trainer_ids[selected_trainer_idx]
            success, msg = add_checklist(
                st.session_state.user_id,
                horse_id,
                jockey_id,
                trainer_id,
                date_of_race.isoformat(),
                memo.strip(),
                finished_place.strip(),
                checklist_data if any(checklist_data.values()) else None
            )
            if success:
                st.success(msg)
            else:
                st.error(msg)

    elif page == "Checklist Review":
        st.header("Checklist Review")
        checklists = get_user_checklists(st.session_state.user_id)
        horses = get_user_horses(st.session_state.user_id)
        jockeys = get_user_jockeys(st.session_state.user_id)
        trainers = get_user_trainers(st.session_state.user_id)
        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]
        jockey_options = ["(No jockey selected)"] + [j["jockey_name"] for j in jockeys]
        jockey_ids = [None] + [j["id"] for j in jockeys]
        trainer_options = ["(No trainer selected)"] + [t["trainer_name"] for t in trainers]
        trainer_ids = [None] + [t["id"] for t in trainers]
        criteria = get_user_criteria(st.session_state.user_id)

        if not checklists:
            st.info("No checklists found.")
        else:
            if "page_num" not in st.session_state:
                st.session_state.page_num = 0
            if "page_size" not in st.session_state:
                st.session_state.page_size = 20
            page_size = st.session_state.page_size
            total_pages = (len(checklists) - 1) // page_size + 1

            # Reset page if page_size changes
            if "last_page_size" not in st.session_state or st.session_state.last_page_size != page_size:
                st.session_state.page_num = 0
                st.session_state.last_page_size = page_size

            page_num = st.session_state.page_num
            start_idx = page_num * page_size
            end_idx = start_idx + page_size
            paged_checklists = checklists[start_idx:end_idx]

            st.caption(f"Showing {start_idx+1}-{min(end_idx, len(checklists))} of {len(checklists)} checklists")

            for entry in paged_checklists:
                with st.expander(f"Horse: {entry['horse_name']} | Jockey: {entry['jockey_name']} | Trainer: {entry['trainer_name']} | Date: {entry['date_of_race']}"):
                    horse_idx = 0
                    if entry["horse_id"] in horse_ids:
                        horse_idx = horse_ids.index(entry["horse_id"])
                    jockey_idx = 0
                    if entry["jockey_id"] in jockey_ids:
                        jockey_idx = jockey_ids.index(entry["jockey_id"])
                    trainer_idx = 0
                    if entry["trainer_id"] in trainer_ids:
                        trainer_idx = trainer_ids.index(entry["trainer_id"])
                    edit_horse_idx = st.selectbox("Horse", range(len(horse_options)), index=horse_idx, format_func=lambda x: horse_options[x], key=f"edit_horse_{entry['id']}")
                    edit_jockey_idx = st.selectbox("Jockey", range(len(jockey_options)), index=jockey_idx, format_func=lambda x: jockey_options[x], key=f"edit_jockey_{entry['id']}")
                    edit_trainer_idx = st.selectbox("Trainer", range(len(trainer_options)), index=trainer_idx, format_func=lambda x: trainer_options[x], key=f"edit_trainer_{entry['id']}")
                    edit_date = st.date_input("Date of Race", value=date.fromisoformat(entry['date_of_race']), key=f"edit_date_{entry['id']}")
                    edit_memo = st.text_area("Memo", value=entry['memo'], key=f"edit_memo_{entry['id']}")
                    edit_finished_place = st.text_input("Finished Place", value=entry['finished_place'], key=f"edit_finished_place_{entry['id']}")
                    edit_checklist_data = {}
                    for c in criteria:
                        prev = entry['checklist'].get(c["criteria_name"], False)
                        edit_checklist_data[c["criteria_name"]] = st.checkbox(c["criteria_name"], value=prev, key=f"edit_check_{entry['id']}_{c['id']}")
                    if st.button("Update", key=f"update_btn_{entry['id']}"):
                        new_horse_id = horse_ids[edit_horse_idx]
                        new_jockey_id = jockey_ids[edit_jockey_idx]
                        new_trainer_id = trainer_ids[edit_trainer_idx]
                        success, msg = update_checklist(
                            entry['id'],
                            st.session_state.user_id,
                            new_horse_id,
                            new_jockey_id,
                            new_trainer_id,
                            edit_date.isoformat(),
                            edit_memo.strip(),
                            edit_finished_place.strip(),
                            edit_checklist_data if any(edit_checklist_data.values()) else None
                        )
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    st.markdown("---")

            # --- Pagination Controls: All on one line ---
            st.markdown(
                """
                <style>
                .pagination-line {
                    display: flex;
                    align-items: center;
                    gap: 0.8em;
                    margin-top: 1em;
                }
                .pagination-btn {
                    padding: 2px 10px;
                    font-size: 0.95em;
                    margin: 0 2px;
                }
                .page-dropdown {
                    min-width: 60px;
                }
                </style>
                """,
                unsafe_allow_html=True
            )

            col1, col2, col3, col4 = st.columns([1.3, 1.1, 1.1, 5])
            with col1:
                new_page_size = st.selectbox("Items per page", [20, 50, 100], index=[20, 50, 100].index(page_size), key="page_size_select", label_visibility="collapsed")
                if new_page_size != page_size:
                    st.session_state.page_size = new_page_size
                    st.session_state.page_num = 0
                    st.rerun()
            with col2:
                # Page number dropdown
                page_options = [f"{i+1}" for i in range(total_pages)]
                selected_page = st.selectbox("Page", page_options, index=page_num, key="page_dropdown", label_visibility="collapsed")
                if int(selected_page) - 1 != page_num:
                    st.session_state.page_num = int(selected_page) - 1
                    st.rerun()
            with col3:
                st.write(f"Page {page_num+1} / {total_pages}")
                next_disabled = page_num >= total_pages - 1
                # if st.button("Next ⟩", key="next_btn", disabled=next_disabled):
                #     st.session_state.page_num += 1
                #     st.rerun()
            with col4:
                prev_disabled = page_num == 0
                # if st.button("⟨ Prev", key="prev_btn", disabled=prev_disabled):
                #     st.session_state.page_num -= 1
                #     st.rerun()

else:
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab2:
        st.header("Register")
        reg_username = st.text_input("Username", key="reg_username_unique")
        reg_display = st.text_input("Display Name", key="reg_display_unique")
        reg_password = st.text_input("Password", type="password", key="reg_password_unique")
        reg_invite = st.text_input("Invitation Code", key="reg_invite_unique")
        register_clicked = st.button("Register", key="register_btn")
        if register_clicked:
            if not reg_username.strip() or not reg_display.strip() or not reg_password.strip() or not reg_invite.strip():
                st.error("Please fill all fields.")
            else:
                success, msg = register_user(reg_username.strip(), reg_display.strip(), reg_password, reg_invite.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    with tab1:
        st.header("Login")
        log_username = st.text_input("Username", key="log_username_unique")
        log_password = st.text_input("Password", type="password", key="log_password_unique")
        login_clicked = st.button("Login", key="login_btn")
        if login_clicked:
            if not log_username.strip() or not log_password.strip():
                st.error("Please fill all fields.")
            else:
                success, disp_name, user_id = login_user(log_username.strip(), log_password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = log_username.strip()
                    st.session_state.display_name = disp_name
                    st.session_state.user_id = user_id
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

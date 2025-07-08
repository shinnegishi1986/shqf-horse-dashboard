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

    # Create checklists table with all columns if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_id INTEGER,
            date_of_race TEXT,
            memo TEXT,
            finished_place TEXT,
            checklist TEXT,
            FOREIGN KEY(owner_id) REFERENCES users(id),
            FOREIGN KEY(horse_id) REFERENCES horses(id)
        )
    ''')

    # Create other tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            criteria_name TEXT NOT NULL,
            UNIQUE(owner_id, criteria_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')

    # Add missing columns to checklists if needed (for upgrades)
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

# User functions
def register_user(username, display_name, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return False, "Username already exists."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cursor.execute("INSERT INTO users (username, display_name, password) VALUES (?, ?, ?)",
                   (username, display_name, hashed))
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

# Horse functions
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

# Criteria functions
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

# Checklist functions
def add_checklist(owner_id, horse_id, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    cursor.execute(
        "INSERT INTO checklists (owner_id, horse_id, date_of_race, memo, finished_place, checklist) VALUES (?, ?, ?, ?, ?, ?)",
        (owner_id, horse_id, date_of_race, memo, finished_place, checklist_json)
    )
    conn.commit()
    conn.close()
    return True, "Checklist saved!"

def update_checklist(checklist_id, owner_id, horse_id, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    cursor.execute(
        "UPDATE checklists SET horse_id=?, date_of_race=?, memo=?, finished_place=?, checklist=? WHERE id=? AND owner_id=?",
        (horse_id, date_of_race, memo, finished_place, checklist_json, checklist_id, owner_id)
    )
    conn.commit()
    conn.close()
    return True, "Checklist updated!"

def get_user_checklists(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT checklists.id, horses.id as horse_id, horses.horse_name, checklists.date_of_race,
               checklists.memo, checklists.finished_place, checklists.checklist
        FROM checklists
        LEFT JOIN horses ON checklists.horse_id = horses.id
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

# --- Main App ---
if st.session_state.logged_in:
    st.sidebar.write(f"Logged in as: {st.session_state.display_name}")
    page = st.sidebar.radio("Menu", ["Register Horse (Template)", "Register Criteria (Template)", "Race Checklist", "Checklist Review"])

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
        criteria = get_user_criteria(st.session_state.user_id)
        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]

        selected_horse_idx = st.selectbox("Select Horse (optional)", range(len(horse_options)), format_func=lambda x: horse_options[x], key="race_horse_select")
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
            success, msg = add_checklist(
                st.session_state.user_id,
                horse_id,
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
        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]
        criteria = get_user_criteria(st.session_state.user_id)
        if not checklists:
            st.info("No checklists found.")
        else:
            for entry in checklists:
                with st.expander(f"Horse: {entry['horse_name']} | Date: {entry['date_of_race']}"):
                    horse_idx = 0
                    if entry["horse_id"] in horse_ids:
                        horse_idx = horse_ids.index(entry["horse_id"])
                    edit_horse_idx = st.selectbox("Horse", range(len(horse_options)), index=horse_idx, format_func=lambda x: horse_options[x], key=f"edit_horse_{entry['id']}")
                    edit_date = st.date_input("Date of Race", value=date.fromisoformat(entry['date_of_race']), key=f"edit_date_{entry['id']}")
                    edit_memo = st.text_area("Memo", value=entry['memo'], key=f"edit_memo_{entry['id']}")
                    edit_finished_place = st.text_input("Finished Place", value=entry['finished_place'], key=f"edit_finished_place_{entry['id']}")
                    edit_checklist_data = {}
                    for c in criteria:
                        prev = entry['checklist'].get(c["criteria_name"], False)
                        edit_checklist_data[c["criteria_name"]] = st.checkbox(c["criteria_name"], value=prev, key=f"edit_check_{entry['id']}_{c['id']}")
                    if st.button("Update", key=f"update_btn_{entry['id']}"):
                        new_horse_id = horse_ids[edit_horse_idx]
                        success, msg = update_checklist(
                            entry['id'],
                            st.session_state.user_id,
                            new_horse_id,
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

else:
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab2:
        st.header("Register")
        reg_username = st.text_input("Username", key="reg_username_unique")
        reg_display = st.text_input("Display Name", key="reg_display_unique")
        reg_password = st.text_input("Password", type="password", key="reg_password_unique")
        register_clicked = st.button("Register", key="register_btn")
        if register_clicked:
            if not reg_username.strip() or not reg_display.strip() or not reg_password.strip():
                st.error("Please fill all fields.")
            else:
                success, msg = register_user(reg_username.strip(), reg_display.strip(), reg_password)
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

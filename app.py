import streamlit as st
import sqlite3
import os
import bcrypt
import json
from datetime import date, datetime


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
            venue_id INTEGER,
            race_name_id INTEGER,
            distance INTEGER,
            date_of_race TEXT,
            memo TEXT,
            finished_place TEXT,
            checklist TEXT,
            FOREIGN KEY(owner_id) REFERENCES users(id),
            FOREIGN KEY(horse_id) REFERENCES horses(id),
            FOREIGN KEY(jockey_id) REFERENCES jockeys(id),
            FOREIGN KEY(trainer_id) REFERENCES trainers(id),
            FOREIGN KEY(venue_id) REFERENCES venues(id),
            FOREIGN KEY(race_name_id) REFERENCES race_names(id)
        )
    ''')
    # --- Column migrations ---
    cursor.execute("PRAGMA table_info(checklists)")
    columns = [row[1] for row in cursor.fetchall()]
    if "jockey_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN jockey_id INTEGER")
    if "trainer_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN trainer_id INTEGER")
    if "venue_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN venue_id INTEGER")
    if "distance" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN distance INTEGER')
    if "date_of_race" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN date_of_race TEXT')
    if "memo" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN memo TEXT')
    if "finished_place" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN finished_place TEXT')
    if "race_name_id" not in columns:
        cursor.execute("ALTER TABLE checklists ADD COLUMN race_name_id INTEGER")
    if "checklist" not in columns:
        cursor.execute('ALTER TABLE checklists ADD COLUMN checklist TEXT')


    # Unique index for owner/horse/date
    cursor.execute("PRAGMA index_list(checklists)")
    indexes = cursor.fetchall()
    index_names = [i[1] for i in indexes]
    if "unique_owner_horse_date" not in index_names:
        try:
            cursor.execute('''
                CREATE UNIQUE INDEX unique_owner_horse_date ON checklists (owner_id, horse_id, date_of_race)
            ''')
        except sqlite3.OperationalError:
            pass


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


    cursor.execute('''
        CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            venue_name TEXT NOT NULL,
            UNIQUE(owner_id, venue_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS race_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        race_name TEXT NOT NULL,
        UNIQUE(owner_id, race_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    )
    ''')


    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --- User Functions (unchanged) ---
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


# --- Horse Functions (unchanged) ---
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

def update_horse(horse_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM horses WHERE owner_id = ? AND horse_name = ? AND id != ?", (owner_id, new_name, horse_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another horse with the same name exists."
    cursor.execute("UPDATE horses SET horse_name = ? WHERE id = ? AND owner_id = ?", (new_name, horse_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Horse updated!"

def delete_horse(horse_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM horses WHERE id = ? AND owner_id = ?", (horse_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Horse deleted!"


def get_user_horses(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, horse_name FROM horses WHERE owner_id = ?", (owner_id,))
    horses = [{"id": row["id"], "horse_name": row["horse_name"]} for row in cursor.fetchall()]
    conn.close()
    return horses


# --- Jockey & Trainer Functions (unchanged) ---
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

def update_jockey(jockey_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jockeys WHERE owner_id = ? AND jockey_name = ? AND id != ?", (owner_id, new_name, jockey_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another jockey with the same name exists."
    cursor.execute("UPDATE jockeys SET jockey_name = ? WHERE id = ? AND owner_id = ?", (new_name, jockey_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Jockey updated!"

def delete_jockey(jockey_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jockeys WHERE id = ? AND owner_id = ?", (jockey_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Jockey deleted!"


def get_user_jockeys(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, jockey_name FROM jockeys WHERE owner_id = ?", (owner_id,))
    jockeys = [{"id": row["id"], "jockey_name": row["jockey_name"]} for row in cursor.fetchall()]
    conn.close()
    return jockeys


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

def update_trainer(trainer_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM trainers WHERE owner_id = ? AND trainer_name = ? AND id != ?", (owner_id, new_name, trainer_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another trainer with the same name exists."
    cursor.execute("UPDATE trainers SET trainer_name = ? WHERE id = ? AND owner_id = ?", (new_name, trainer_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Trainer updated!"

def delete_trainer(trainer_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trainers WHERE id = ? AND owner_id = ?", (trainer_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Trainer deleted!"


def get_user_trainers(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, trainer_name FROM trainers WHERE owner_id = ?", (owner_id,))
    trainers = [{"id": row["id"], "trainer_name": row["trainer_name"]} for row in cursor.fetchall()]
    conn.close()
    return trainers


# --- Venue Functions ---
def add_venue(owner_id, venue_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM venues WHERE owner_id = ? AND venue_name = ?", (owner_id, venue_name))
    if cursor.fetchone():
        conn.close()
        return False, "Venue already registered."
    cursor.execute("INSERT INTO venues (owner_id, venue_name) VALUES (?, ?)", (owner_id, venue_name))
    conn.commit()
    conn.close()
    return True, "Venue registered!"


def get_user_venues(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, venue_name FROM venues WHERE owner_id = ?", (owner_id,))
    venues = [{"id": row["id"], "venue_name": row["venue_name"]} for row in cursor.fetchall()]
    conn.close()
    return venues


def update_venue(venue_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM venues WHERE owner_id = ? AND venue_name = ? AND id != ?", (owner_id, new_name, venue_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another venue with the same name exists."
    cursor.execute("UPDATE venues SET venue_name = ? WHERE id = ? AND owner_id = ?", (new_name, venue_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Venue updated!"


def delete_venue(venue_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM venues WHERE id = ? AND owner_id = ?", (venue_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Venue deleted!"

# --- Race Name Functions ---
def add_race_name(owner_id, race_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM race_names WHERE owner_id = ? AND race_name = ?", (owner_id, race_name))
    if cursor.fetchone():
        conn.close()
        return False, "Race name already registered."
    cursor.execute("INSERT INTO race_names (owner_id, race_name) VALUES (?, ?)", (owner_id, race_name))
    conn.commit()
    conn.close()
    return True, "Race name registered!"

def get_user_race_names(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, race_name FROM race_names WHERE owner_id = ?", (owner_id,))
    races = [{"id": row["id"], "race_name": row["race_name"]} for row in cursor.fetchall()]
    conn.close()
    return races

def update_race_name(race_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM race_names WHERE owner_id = ? AND race_name = ? AND id != ?", (owner_id, new_name, race_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another race with the same name exists."
    cursor.execute("UPDATE race_names SET race_name = ? WHERE id = ? AND owner_id = ?", (new_name, race_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Race name updated!"

def delete_race_name(race_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM race_names WHERE id = ? AND owner_id = ?", (race_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Race name deleted!"



# --- Criteria Functions (with update/delete) ---
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


def update_criteria(criteria_id, owner_id, new_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM criteria WHERE owner_id = ? AND criteria_name = ? AND id != ?", (owner_id, new_name, criteria_id))
    if cursor.fetchone():
        conn.close()
        return False, "Another criteria with the same name exists."
    cursor.execute("UPDATE criteria SET criteria_name = ? WHERE id = ? AND owner_id = ?", (new_name, criteria_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Criteria updated!"


def delete_criteria(criteria_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM criteria WHERE id = ? AND owner_id = ?", (criteria_id, owner_id))
    conn.commit()
    conn.close()
    return True, "Criteria deleted!"


# --- Checklist Functions (venue_id and distance added) ---
def add_checklist(owner_id, horse_id, jockey_id, trainer_id, venue_id, race_name_id, distance, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    if horse_id is not None and date_of_race:
        cursor.execute('''
            SELECT id FROM checklists WHERE owner_id=? AND horse_id=? AND date_of_race=?
        ''', (owner_id, horse_id, date_of_race))
        if cursor.fetchone():
            conn.close()
            return False, "A checklist for this horse and race date is already registered."
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    try:
        cursor.execute(
            "INSERT INTO checklists (owner_id, horse_id, jockey_id, trainer_id, venue_id, race_name_id, distance, date_of_race, memo, finished_place, checklist) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, horse_id, jockey_id, trainer_id, venue_id, race_name_id, distance, date_of_race, memo, finished_place, checklist_json)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, "A checklist for this horse and race date is already registered."
    conn.close()
    return True, "Checklist saved!"


def update_checklist(checklist_id, owner_id, horse_id, jockey_id, trainer_id, venue_id, race_name_id, distance, date_of_race, memo, finished_place, checklist_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    if horse_id is not None and date_of_race:
        cursor.execute('''
            SELECT id FROM checklists WHERE owner_id=? AND horse_id=? AND date_of_race=? AND id<>?
        ''', (owner_id, horse_id, date_of_race, checklist_id))
        if cursor.fetchone():
            conn.close()
            return False, "Another checklist for this horse and race date is already registered."
    checklist_json = json.dumps(checklist_data) if checklist_data else None
    cursor.execute(
        "UPDATE checklists SET horse_id=?, jockey_id=?, trainer_id=?, venue_id=?, race_name_id=?, distance=?, date_of_race=?, memo=?, finished_place=?, checklist=? WHERE id=? AND owner_id=?",
        (horse_id, jockey_id, trainer_id, venue_id, race_name_id, distance, date_of_race, memo, finished_place, checklist_json, checklist_id, owner_id)
    )
    conn.commit()
    conn.close()
    return True, "Checklist updated!"


def get_user_checklists(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT checklists.id,
            horses.id as horse_id, horses.horse_name,
            jockeys.id as jockey_id, jockeys.jockey_name,
            trainers.id as trainer_id, trainers.trainer_name,
            venues.id as venue_id, venues.venue_name,
            race_names.id as race_name_id, race_names.race_name,
            checklists.distance,
            checklists.date_of_race, checklists.memo, checklists.finished_place, checklists.checklist
        FROM checklists
        LEFT JOIN horses ON checklists.horse_id = horses.id
        LEFT JOIN jockeys ON checklists.jockey_id = jockeys.id
        LEFT JOIN trainers ON checklists.trainer_id = trainers.id
        LEFT JOIN venues ON checklists.venue_id = venues.id
        LEFT JOIN race_names ON checklists.race_name_id = race_names.id
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
            "venue_id": row['venue_id'],
            "venue_name": row['venue_name'] if row['venue_name'] else "(No venue selected)",
            "race_name_id": row['race_name_id'],
            "race_name": row['race_name'] if row['race_name'] else "(No race name selected)",
            "distance": row['distance'],
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
        "Register Venue (Template)",
        "Register Race Name (Template)",
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
        # ▼▼▼ Add these lines for LIST/EDIT/DELETE ▼▼▼
        st.write("### Edit/Delete Registered Horses")
        horse_list = get_user_horses(st.session_state.user_id)
        if not horse_list:
            st.info("No horses registered yet.")
        for horse in horse_list:
            with st.expander(f"Horse: {horse['horse_name']}"):
                new_name = st.text_input("Edit Horse Name", value=horse['horse_name'], key=f"edit_horse_{horse['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_horse_btn_{horse['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a horse name.")
                        else:
                            # Add an update_horse function like update_venue
                            success, msg = update_horse(horse['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_horse_btn_{horse['id']}"):
                        # Add a delete_horse function like delete_venue
                        delete_horse(horse['id'], st.session_state.user_id)
                        st.success("Horse deleted.")
                        st.rerun()


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
        # ▼▼▼ Add these lines for LIST/EDIT/DELETE ▼▼▼
        st.write("### Edit/Delete Registered Jockeys")
        jockey_list = get_user_jockeys(st.session_state.user_id)
        if not jockey_list:
            st.info("No jockeys registered yet.")
        for jockey in jockey_list:
            with st.expander(f"Jockey: {jockey['jockey_name']}"):
                new_name = st.text_input("Edit Jockey Name", value=jockey['jockey_name'], key=f"edit_jockey_{jockey['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_jockey_btn_{jockey['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a jockey name.")
                        else:
                            success, msg = update_jockey(jockey['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_jockey_btn_{jockey['id']}"):
                        delete_jockey(jockey['id'], st.session_state.user_id)
                        st.success("Jockey deleted.")
                        st.rerun()


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
        # ▼▼▼ Add these lines for LIST/EDIT/DELETE ▼▼▼
        st.write("### Edit/Delete Registered Trainers")
        trainer_list = get_user_trainers(st.session_state.user_id)
        if not trainer_list:
            st.info("No trainers registered yet.")
        for trainer in trainer_list:
            with st.expander(f"Trainer: {trainer['trainer_name']}"):
                new_name = st.text_input("Edit Trainer Name", value=trainer['trainer_name'], key=f"edit_trainer_{trainer['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_trainer_btn_{trainer['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a trainer name.")
                        else:
                            success, msg = update_trainer(trainer['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_trainer_btn_{trainer['id']}"):
                        delete_trainer(trainer['id'], st.session_state.user_id)
                        st.success("Trainer deleted.")
                        st.rerun()


    elif page == "Register Venue (Template)":
        st.header("Register a Venue (Racecourse) Template")
        venue_name = st.text_input("Venue Name (e.g., Tokyo)", key="venue_name_input")
        add_venue_clicked = st.button("Add Venue", key="add_venue_btn")
        if add_venue_clicked:
            if not venue_name.strip():
                st.error("Please enter a venue name.")
            else:
                success, msg = add_venue(st.session_state.user_id, venue_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        st.write("### Edit/Delete Registered Venues")
        venue_list = get_user_venues(st.session_state.user_id)
        if not venue_list:
            st.info("No venues registered yet.")
        for venue in venue_list:
            with st.expander(f"Venue: {venue['venue_name']}"):
                new_name = st.text_input("Edit Venue Name", value=venue['venue_name'], key=f"edit_venue_{venue['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_venue_btn_{venue['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a venue name.")
                        else:
                            success, msg = update_venue(venue['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_venue_btn_{venue['id']}"):
                        delete_venue(venue['id'], st.session_state.user_id)
                        st.success("Venue deleted.")
                        st.rerun()

    elif page == "Register Race Name (Template)":
        st.header("Register a Race Name Template")
        race_name = st.text_input("Race Name", key="race_name_input")
        add_race_clicked = st.button("Add Race Name", key="add_race_btn")
        if add_race_clicked:
            if not race_name.strip():
                st.error("Please enter a race name.")
            else:
                success, msg = add_race_name(st.session_state.user_id, race_name.strip())
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

        st.write("### Edit/Delete Registered Race Names")
        race_list = get_user_race_names(st.session_state.user_id)
        if not race_list:
            st.info("No race names registered yet.")
        for race in race_list:
            with st.expander(f"Race Name: {race['race_name']}"):
                new_name = st.text_input("Edit Race Name", value=race['race_name'], key=f"edit_race_{race['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_race_btn_{race['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a race name.")
                        else:
                            success, msg = update_race_name(race['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_race_btn_{race['id']}"):
                        delete_race_name(race['id'], st.session_state.user_id)
                        st.success("Race name deleted.")
                        st.rerun()


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


        st.write("### Edit/Delete Registered Criteria")
        criteria_list = get_user_criteria(st.session_state.user_id)
        if not criteria_list:
            st.info("No criteria registered yet.")
        for crit in criteria_list:
            with st.expander(f"Criteria: {crit['criteria_name']}"):
                new_name = st.text_input("Edit Criteria Name", value=crit['criteria_name'], key=f"edit_criteria_{crit['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Update", key=f"update_criteria_btn_{crit['id']}"):
                        if not new_name.strip():
                            st.error("Please enter a criteria name.")
                        else:
                            success, msg = update_criteria(crit['id'], st.session_state.user_id, new_name.strip())
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                with col2:
                    if st.button("Delete", key=f"delete_criteria_btn_{crit['id']}"):
                        delete_criteria(crit['id'], st.session_state.user_id)
                        st.success("Criteria deleted.")
                        st.rerun()


    elif page == "Race Checklist":
        st.header("Race Checklist")
        horses = get_user_horses(st.session_state.user_id)
        jockeys = get_user_jockeys(st.session_state.user_id)
        trainers = get_user_trainers(st.session_state.user_id)
        venues = get_user_venues(st.session_state.user_id)
        race_names = get_user_race_names(st.session_state.user_id)
        criteria = get_user_criteria(st.session_state.user_id)


        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]
        jockey_options = ["(No jockey selected)"] + [j["jockey_name"] for j in jockeys]
        jockey_ids = [None] + [j["id"] for j in jockeys]
        trainer_options = ["(No trainer selected)"] + [t["trainer_name"] for t in trainers]
        trainer_ids = [None] + [t["id"] for t in trainers]
        venue_options = ["(No venue selected)"] + [v["venue_name"] for v in venues]
        venue_ids = [None] + [v["id"] for v in venues]
        race_options = ["(No race name selected)"] + [r["race_name"] for r in race_names]
        race_ids = [None] + [r["id"] for r in race_names]

        selected_horse_idx = st.selectbox("Select Horse (optional)", range(len(horse_options)), format_func=lambda x: horse_options[x], key="race_horse_select")
        selected_jockey_idx = st.selectbox("Select Jockey (optional)", range(len(jockey_options)), format_func=lambda x: jockey_options[x], key="race_jockey_select")
        selected_trainer_idx = st.selectbox("Select Trainer (optional)", range(len(trainer_options)), format_func=lambda x: trainer_options[x], key="race_trainer_select")
        selected_venue_idx = st.selectbox("Select Venue (optional)", range(len(venue_options)), format_func=lambda x: venue_options[x], key="race_venue_select")
        selected_race_idx = st.selectbox("Select Race Name (optional)", range(len(race_options)), format_func=lambda x: race_options[x], key="race_race_select")
        distance = st.number_input("Distance (meters)", min_value=0, max_value=5000, value=0, step=100, key="race_distance_input")    
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
            venue_id = venue_ids[selected_venue_idx]
            race_name_id = race_ids[selected_race_idx]
            success, msg = add_checklist(
                st.session_state.user_id,
                horse_id,
                jockey_id,
                trainer_id,
                venue_id,
                race_name_id,
                distance if distance > 0 else None,
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
        venues = get_user_venues(st.session_state.user_id)
        race_names = get_user_race_names(st.session_state.user_id)
        horse_options = ["(No horse selected)"] + [h["horse_name"] for h in horses]
        horse_ids = [None] + [h["id"] for h in horses]
        jockey_options = ["(No jockey selected)"] + [j["jockey_name"] for j in jockeys]
        jockey_ids = [None] + [j["id"] for j in jockeys]
        trainer_options = ["(No trainer selected)"] + [t["trainer_name"] for t in trainers]
        trainer_ids = [None] + [t["id"] for t in trainers]
        venue_options = ["(No venue selected)"] + [v["venue_name"] for v in venues]
        venue_ids = [None] + [v["id"] for v in venues]
        race_options = ["(No race name selected)"] + [r["race_name"] for r in race_names]
        race_ids = [None] + [r["id"] for r in race_names]
        criteria = get_user_criteria(st.session_state.user_id)


        with st.expander("🔍 Search & Filter Checklists", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                filter_horse_idx = st.selectbox("Filter by Horse", range(len(horse_options)), format_func=lambda x: horse_options[x], key="filter_horse")
                filter_jockey_idx = st.selectbox("Filter by Jockey", range(len(jockey_options)), format_func=lambda x: jockey_options[x], key="filter_jockey")
                filter_trainer_idx = st.selectbox("Filter by Trainer", range(len(trainer_options)), format_func=lambda x: trainer_options[x], key="filter_trainer")
                filter_venue_idx = st.selectbox("Filter by Venue", range(len(venue_options)), format_func=lambda x: venue_options[x], key="filter_venue")
                filter_race_idx = st.selectbox("Filter by Race Name", range(len(race_options)), format_func=lambda x: race_options[x], key="filter_race")
                # --- Add a memo keyword filter box ---
                filter_memo_keyword = st.text_input("Memo contains keyword (optional)", value="", key="filter_memo_keyword")
            with col2:
                filter_criteria = st.multiselect("Filter by Criteria (must match all selected)", [c["criteria_name"] for c in criteria], key="filter_criteria")
                filter_distance_from = st.number_input("From Distance (meters)", min_value=0, max_value=5000, value=0, step=100, key="filter_distance_from")
                filter_distance_to = st.number_input("To Distance (meters)", min_value=0, max_value=5000, value=5000, step=100, key="filter_distance_to")
                filter_date_from = st.date_input("From Date", value=None, key="filter_date_from")
                filter_date_to = st.date_input("To Date", value=None, key="filter_date_to")


        filtered_checklists = []
        for entry in checklists:
            if filter_horse_idx != 0 and entry["horse_id"] != horse_ids[filter_horse_idx]:
                continue
            if filter_jockey_idx != 0 and entry["jockey_id"] != jockey_ids[filter_jockey_idx]:
                continue
            if filter_trainer_idx != 0 and entry["trainer_id"] != trainer_ids[filter_trainer_idx]:
                continue
            if filter_venue_idx != 0 and entry["venue_id"] != venue_ids[filter_venue_idx]:
                continue
            if filter_race_idx != 0 and entry.get("race_name_id") != race_ids[filter_race_idx]:
                continue
            entry_date = None
            try:
                entry_date = datetime.strptime(entry['date_of_race'], "%Y-%m-%d").date()
            except Exception:
                pass
            if filter_date_from and entry_date and entry_date < filter_date_from:
                continue
            if filter_date_to and entry_date and entry_date > filter_date_to:
                continue
            if filter_criteria:
                if not entry["checklist"]:
                    continue
                if not all(entry["checklist"].get(c, False) for c in filter_criteria):
                            continue
            distance = entry["distance"] if entry["distance"] is not None else 0
            if (filter_distance_from is not None and distance < filter_distance_from):
                continue
            if (filter_distance_to is not None and distance > filter_distance_to):
                continue
            if filter_memo_keyword and filter_memo_keyword.strip():
                if filter_memo_keyword.strip().lower() not in (entry['memo'] or "").lower():
                    continue
            filtered_checklists.append(entry)


        # --- Statistics ---
        if filtered_checklists:
            shown = [x for x in filtered_checklists if str(x['finished_place']).strip().isdigit()]
            first = [x for x in shown if int(x['finished_place']) == 1]
            within3 = [x for x in shown if int(x['finished_place']) in (1,2,3)]
            st.markdown(
                f"**Filtered Results:** {len(filtered_checklists)} races.  \n"
                f"・Probability (Finished within 3rd):  "
                +
                (f"{(len(within3)/len(filtered_checklists)*100):.1f}%" if filtered_checklists else "-")
                + "　/　"
                f"・Probability (Won):  "
                + (f"{(len(first)/len(filtered_checklists)*100):.1f}%" if filtered_checklists else "-")
            )


        if not filtered_checklists:
            st.info("No checklists found with the selected filters.")
        else:
            if "page_num" not in st.session_state:
                st.session_state.page_num = 0
            if "page_size" not in st.session_state:
                st.session_state.page_size = 20
            page_size = st.session_state.page_size


            total_pages = (len(filtered_checklists) - 1) // page_size + 1 if len(filtered_checklists) > 0 else 1


            if "last_page_size" not in st.session_state or st.session_state.last_page_size != page_size:
                st.session_state.page_num = 0
                st.session_state.last_page_size = page_size


            if st.session_state.page_num >= total_pages:
                st.session_state.page_num = max(total_pages - 1, 0)


            page_num = st.session_state.page_num
            start_idx = page_num * page_size
            end_idx = start_idx + page_size
            paged_checklists = filtered_checklists[start_idx:end_idx]


            st.caption(f"Showing {start_idx+1}-{min(end_idx, len(filtered_checklists))} of {len(filtered_checklists)} checklists")


            for entry in paged_checklists:
                expander_title = f"Horse: {entry['horse_name']} | Jockey: {entry['jockey_name']} | Trainer: {entry['trainer_name']} | Venue: {entry['venue_name']} | Race Name: {entry.get('race_name', '(No race name selected)')} | Distance: {entry['distance']}m | Date: {entry['date_of_race']} | Finished Place: {entry['finished_place']}"
                with st.expander(expander_title):
                    horse_idx = 0
                    if entry["horse_id"] in horse_ids:
                        horse_idx = horse_ids.index(entry["horse_id"])
                    jockey_idx = 0
                    if entry["jockey_id"] in jockey_ids:
                        jockey_idx = jockey_ids.index(entry["jockey_id"])
                    trainer_idx = 0
                    if entry["trainer_id"] in trainer_ids:
                        trainer_idx = trainer_ids.index(entry["trainer_id"])
                    venue_idx = 0
                    if entry["venue_id"] in venue_ids:
                        venue_idx = venue_ids.index(entry["venue_id"])
                    # --------- Add for race name ---------
                    race_idx = 0
                    if "race_name_id" in entry and entry["race_name_id"] in race_ids:
                        race_idx = race_ids.index(entry["race_name_id"])
                    edit_horse_idx = st.selectbox("Horse", range(len(horse_options)), index=horse_idx, format_func=lambda x: horse_options[x], key=f"edit_horse_{entry['id']}")
                    edit_jockey_idx = st.selectbox("Jockey", range(len(jockey_options)), index=jockey_idx, format_func=lambda x: jockey_options[x], key=f"edit_jockey_{entry['id']}")
                    edit_trainer_idx = st.selectbox("Trainer", range(len(trainer_options)), index=trainer_idx, format_func=lambda x: trainer_options[x], key=f"edit_trainer_{entry['id']}")
                    edit_venue_idx = st.selectbox("Venue", range(len(venue_options)), index=venue_idx, format_func=lambda x: venue_options[x], key=f"edit_venue_{entry['id']}")
                    # --------- Add the race name selectbox ---------
                    edit_race_idx = st.selectbox("Race Name", range(len(race_options)), index=race_idx, format_func=lambda x: race_options[x], key=f"edit_race_{entry['id']}")
                    edit_distance = st.number_input("Distance (meters)", min_value=0, max_value=5000, value=entry.get('distance') or 0, step=100, key=f"edit_distance_{entry['id']}")
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
                        new_venue_id = venue_ids[edit_venue_idx]
                        new_race_id = race_ids[edit_race_idx] 
                        success, msg = update_checklist(
                            entry['id'],
                            st.session_state.user_id,
                            new_horse_id,
                            new_jockey_id,
                            new_trainer_id,
                            new_venue_id,
                            new_race_id,
                            edit_distance if edit_distance > 0 else None,
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
                page_options = [f"{i+1}" for i in range(total_pages)]
                selected_page = st.selectbox("Page", page_options, index=page_num, key="page_dropdown", label_visibility="collapsed")
                if int(selected_page) - 1 != page_num:
                    st.session_state.page_num = int(selected_page) - 1
                    st.rerun()
            with col3:
                st.write(f"Page {page_num+1} / {total_pages}")
            with col4:
                pass  # reserved for future


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

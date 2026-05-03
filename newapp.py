import streamlit as st
import sqlite3
import os
import bcrypt
import json
from datetime import date, datetime
import pandas as pd
import io

DB_PATH = "data/horse_checklist_app.db"


# =========================
# Database
# =========================
def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
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
        program_number INTEGER,
        number_of_horses INTEGER,
        odds REAL,
        prize REAL,
        bracket_number INTEGER,
        horse_number INTEGER,
        track_condition TEXT,
        race_class TEXT,
        pace_scenario TEXT,
        draw_bias_note TEXT,
        checklist_score REAL,
        estimated_win_probability REAL,
        fair_odds REAL,
        implied_probability REAL,
        edge_percent REAL,
        decision_type TEXT,
        bet_type TEXT,
        bookmaker TEXT,
        stake REAL,
        bankroll_before REAL,
        suggested_kelly_fraction REAL,
        suggested_kelly_stake REAL,
        is_locked INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(owner_id) REFERENCES users(id),
        FOREIGN KEY(horse_id) REFERENCES horses(id),
        FOREIGN KEY(jockey_id) REFERENCES jockeys(id),
        FOREIGN KEY(trainer_id) REFERENCES trainers(id),
        FOREIGN KEY(venue_id) REFERENCES venues(id),
        FOREIGN KEY(race_name_id) REFERENCES race_names(id)
    );
    """)

    cursor.execute("PRAGMA table_info(checklists)")
    columns = [row[1] for row in cursor.fetchall()]
    migrations = {
        "jockey_id": "INTEGER",
        "trainer_id": "INTEGER",
        "venue_id": "INTEGER",
        "distance": "INTEGER",
        "date_of_race": "TEXT",
        "memo": "TEXT",
        "finished_place": "TEXT",
        "race_name_id": "INTEGER",
        "checklist": "TEXT",
        "program_number": "INTEGER",
        "number_of_horses": "INTEGER",
        "odds": "REAL",
        "prize": "REAL",
        "bracket_number": "INTEGER",
        "horse_number": "INTEGER",
        "track_condition": "TEXT",
        "race_class": "TEXT",
        "pace_scenario": "TEXT",
        "draw_bias_note": "TEXT",
        "checklist_score": "REAL",
        "estimated_win_probability": "REAL",
        "fair_odds": "REAL",
        "implied_probability": "REAL",
        "edge_percent": "REAL",
        "decision_type": "TEXT",
        "bet_type": "TEXT",
        "bookmaker": "TEXT",
        "stake": "REAL",
        "bankroll_before": "REAL",
        "suggested_kelly_fraction": "REAL",
        "suggested_kelly_stake": "REAL",
        "is_locked": "INTEGER DEFAULT 0",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }
    for col, col_type in migrations.items():
        if col not in columns:
            cursor.execute(f"ALTER TABLE checklists ADD COLUMN {col} {col_type}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        password TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invitation_codes (
        code TEXT PRIMARY KEY,
        used INTEGER DEFAULT 0
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS horses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        horse_name TEXT NOT NULL,
        UNIQUE(owner_id, horse_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jockeys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        jockey_name TEXT NOT NULL,
        UNIQUE(owner_id, jockey_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trainers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        trainer_name TEXT NOT NULL,
        UNIQUE(owner_id, trainer_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS criteria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        criteria_name TEXT NOT NULL,
        UNIQUE(owner_id, criteria_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS venues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        venue_name TEXT NOT NULL,
        UNIQUE(owner_id, venue_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS race_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        race_name TEXT NOT NULL,
        UNIQUE(owner_id, race_name),
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    """)

    cursor.execute("PRAGMA index_list(checklists)")
    indexes = cursor.fetchall()
    index_names = [i[1] for i in indexes]
    if "unique_owner_horse_date" not in index_names:
        try:
            cursor.execute("""
            CREATE UNIQUE INDEX unique_owner_horse_date
            ON checklists (owner_id, horse_id, date_of_race)
            """)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# Utility
# =========================
def safe_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def safe_int(x):
    try:
        if x is None or x == "":
            return None
        return int(x)
    except Exception:
        return None


def normalize_date(date_val):
    if pd.isna(date_val) or not date_val:
        return None
    if isinstance(date_val, (datetime, pd.Timestamp)):
        return date_val.date().strftime("%Y-%m-%d")

    date_str = str(date_val).strip()
    if " " in date_str:
        date_str = date_str.split(" ")[0]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue

    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def calc_implied_probability(odds):
    if odds and odds > 0:
        return 1 / odds
    return None


def calc_fair_odds(prob_percent):
    if prob_percent and prob_percent > 0:
        return 100 / prob_percent
    return None


def calc_edge_percent(estimated_prob_percent, market_odds):
    if estimated_prob_percent and market_odds and market_odds > 0:
        return estimated_prob_percent - ((1 / market_odds) * 100)
    return None


def calc_kelly_fraction_decimal_odds(prob_percent, decimal_odds):
    if not prob_percent or not decimal_odds or decimal_odds <= 1:
        return 0.0
    p = prob_percent / 100
    q = 1 - p
    b = decimal_odds - 1
    k = ((b * p) - q) / b
    return max(0.0, k)


def calc_profit(decision_type, odds, stake, finished_place, bet_type):
    if decision_type != "BET":
        return 0.0
    if not stake or stake <= 0:
        return 0.0

    place = None
    s = str(finished_place).strip() if finished_place is not None else ""
    if s.isdigit():
        place = int(s)

    if bet_type == "WIN":
        if place == 1 and odds and odds > 0:
            return stake * (odds - 1)
        return -stake

    if bet_type == "PLACE":
        if place is not None and place <= 3 and odds and odds > 0:
            return stake * (odds - 1)
        return -stake

    if bet_type == "EACH_WAY":
        half = stake / 2
        profit = -stake
        if odds and odds > 0:
            if place == 1:
                profit = (half * (odds - 1)) + (half * ((odds / 4) - 1))
            elif place is not None and place <= 3:
                profit = -half + (half * ((odds / 4) - 1))
        return profit

    return 0.0


def checklist_score_from_dict(checklist_dict):
    if not checklist_dict:
        return 0
    return sum(1 for _, v in checklist_dict.items() if v)


def get_entity_options(items, label_key):
    return ["(No selection)"] + [x[label_key] for x in items], [None] + [x["id"] for x in items]


def idx_or_zero(arr, value):
    return arr.index(value) if value in arr else 0


def to_csv_download(df, filename):
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"Download {filename}",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
    )


# =========================
# Auth
# =========================
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
    if code_row["used"]:
        conn.close()
        return False, "Invitation code has already been used."

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cursor.execute(
        "INSERT INTO users (username, display_name, password) VALUES (?, ?, ?)",
        (username, display_name, hashed),
    )
    cursor.execute(
        "UPDATE invitation_codes SET used = 1 WHERE code = ?",
        (invitation_code,),
    )

    conn.commit()
    conn.close()
    return True, "Registration successful!"


def login_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and bcrypt.checkpw(password.encode(), user["password"].encode()):
        return True, user["display_name"], user["id"]
    return False, None, None


def add_invitation_code(code):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO invitation_codes (code, used) VALUES (?, 0)",
            (code,),
        )
        conn.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False
    conn.close()
    return result


# =========================
# Master CRUD
# =========================
def add_simple_item(table, owner_id, col_name, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"INSERT INTO {table} (owner_id, {col_name}) VALUES (?, ?)",
            (owner_id, value),
        )
        conn.commit()
        conn.close()
        return True, f"{table[:-1].capitalize()} added!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"{table[:-1].capitalize()} already exists."


def update_simple_item(table, item_id, owner_id, col_name, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE {table} SET {col_name} = ? WHERE id = ? AND owner_id = ?",
            (value, item_id, owner_id),
        )
        conn.commit()
        conn.close()
        return True, f"{table[:-1].capitalize()} updated!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Another item with the same name exists."


def delete_simple_item(table, item_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {table} WHERE id = ? AND owner_id = ?", (item_id, owner_id))
    conn.commit()
    conn.close()
    return True, f"{table[:-1].capitalize()} deleted!"


def get_simple_items(table, owner_id, col_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id, {col_name} FROM {table} WHERE owner_id = ? ORDER BY {col_name}",
        (owner_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r["id"], col_name: r[col_name]} for r in rows]


def add_horse(owner_id, horse_name): return add_simple_item("horses", owner_id, "horse_name", horse_name)
def update_horse(horse_id, owner_id, new_name): return update_simple_item("horses", horse_id, owner_id, "horse_name", new_name)
def delete_horse(horse_id, owner_id): return delete_simple_item("horses", horse_id, owner_id)
def get_user_horses(owner_id): return get_simple_items("horses", owner_id, "horse_name")

def add_jockey(owner_id, jockey_name): return add_simple_item("jockeys", owner_id, "jockey_name", jockey_name)
def update_jockey(jockey_id, owner_id, new_name): return update_simple_item("jockeys", jockey_id, owner_id, "jockey_name", new_name)
def delete_jockey(jockey_id, owner_id): return delete_simple_item("jockeys", jockey_id, owner_id)
def get_user_jockeys(owner_id): return get_simple_items("jockeys", owner_id, "jockey_name")

def add_trainer(owner_id, trainer_name): return add_simple_item("trainers", owner_id, "trainer_name", trainer_name)
def update_trainer(trainer_id, owner_id, new_name): return update_simple_item("trainers", trainer_id, owner_id, "trainer_name", new_name)
def delete_trainer(trainer_id, owner_id): return delete_simple_item("trainers", trainer_id, owner_id)
def get_user_trainers(owner_id): return get_simple_items("trainers", owner_id, "trainer_name")

def add_venue(owner_id, venue_name): return add_simple_item("venues", owner_id, "venue_name", venue_name)
def update_venue(venue_id, owner_id, new_name): return update_simple_item("venues", venue_id, owner_id, "venue_name", new_name)
def delete_venue(venue_id, owner_id): return delete_simple_item("venues", venue_id, owner_id)
def get_user_venues(owner_id): return get_simple_items("venues", owner_id, "venue_name")

def add_race_name(owner_id, race_name): return add_simple_item("race_names", owner_id, "race_name", race_name)
def update_race_name(race_id, owner_id, new_name): return update_simple_item("race_names", race_id, owner_id, "race_name", new_name)
def delete_race_name(race_id, owner_id): return delete_simple_item("race_names", race_id, owner_id)
def get_user_race_names(owner_id): return get_simple_items("race_names", owner_id, "race_name")

def add_criteria(owner_id, criteria_name): return add_simple_item("criteria", owner_id, "criteria_name", criteria_name)
def update_criteria(criteria_id, owner_id, new_name): return update_simple_item("criteria", criteria_id, owner_id, "criteria_name", new_name)
def delete_criteria(criteria_id, owner_id): return delete_simple_item("criteria", criteria_id, owner_id)
def get_user_criteria(owner_id): return get_simple_items("criteria", owner_id, "criteria_name")


# =========================
# Checklist CRUD
# =========================
def add_checklist_record(payload):
    conn = get_db_connection()
    cursor = conn.cursor()

    if payload["horse_id"] is not None and payload["date_of_race"]:
        cursor.execute(
            "SELECT id FROM checklists WHERE owner_id = ? AND horse_id = ? AND date_of_race = ?",
            (payload["owner_id"], payload["horse_id"], payload["date_of_race"]),
        )
        if cursor.fetchone():
            conn.close()
            return False, "A checklist for this horse and race date is already registered."

    cols = list(payload.keys())
    vals = [payload[c] for c in cols]
    placeholders = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)

    try:
        cursor.execute(f"INSERT INTO checklists ({col_sql}) VALUES ({placeholders})", vals)
        conn.commit()
        conn.close()
        return True, "Checklist saved!"
    except sqlite3.IntegrityError as e:
        conn.close()
        return False, f"Save failed: {e}"


def update_checklist_record(checklist_id, owner_id, payload):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT is_locked FROM checklists WHERE id = ? AND owner_id = ?", (checklist_id, owner_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Checklist not found."
    if row["is_locked"]:
        conn.close()
        return False, "This record is locked and cannot be edited."

    horse_id = payload.get("horse_id")
    date_of_race = payload.get("date_of_race")
    if horse_id is not None and date_of_race:
        cursor.execute(
            "SELECT id FROM checklists WHERE owner_id = ? AND horse_id = ? AND date_of_race = ? AND id != ?",
            (owner_id, horse_id, date_of_race, checklist_id),
        )
        if cursor.fetchone():
            conn.close()
            return False, "Another checklist for this horse and race date is already registered."

    set_sql = ", ".join([f"{k} = ?" for k in payload.keys()])
    vals = list(payload.values()) + [checklist_id, owner_id]
    cursor.execute(f"UPDATE checklists SET {set_sql} WHERE id = ? AND owner_id = ?", vals)
    conn.commit()
    conn.close()
    return True, "Checklist updated!"


def lock_checklist(checklist_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE checklists SET is_locked = 1 WHERE id = ? AND owner_id = ?",
        (checklist_id, owner_id),
    )
    conn.commit()
    conn.close()


def delete_checklist(checklist_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM checklists WHERE id = ? AND owner_id = ? AND is_locked = 0",
        (checklist_id, owner_id),
    )
    conn.commit()
    conn.close()


def get_user_checklists(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.*,
            h.horse_name,
            j.jockey_name,
            t.trainer_name,
            v.venue_name,
            r.race_name
        FROM checklists c
        LEFT JOIN horses h
            ON c.horse_id = h.id AND h.owner_id = c.owner_id
        LEFT JOIN jockeys j
            ON c.jockey_id = j.id AND j.owner_id = c.owner_id
        LEFT JOIN trainers t
            ON c.trainer_id = t.id AND t.owner_id = c.owner_id
        LEFT JOIN venues v
            ON c.venue_id = v.id AND v.owner_id = c.owner_id
        LEFT JOIN race_names r
            ON c.race_name_id = r.id AND r.owner_id = c.owner_id
        WHERE c.owner_id = ?
        ORDER BY c.date_of_race DESC, c.id DESC
    """, (owner_id,))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        try:
            checklist_data = json.loads(d["checklist"]) if d["checklist"] else {}
        except Exception:
            checklist_data = {}

        d["horse_name"] = d["horse_name"] if d["horse_name"] else f"(Missing horse id: {d['horse_id']})" if d["horse_id"] else "No horse selected"
        d["jockey_name"] = d["jockey_name"] if d["jockey_name"] else f"(Missing jockey id: {d['jockey_id']})" if d["jockey_id"] else "No jockey selected"
        d["trainer_name"] = d["trainer_name"] if d["trainer_name"] else f"(Missing trainer id: {d['trainer_id']})" if d["trainer_id"] else "No trainer selected"
        d["venue_name"] = d["venue_name"] if d["venue_name"] else f"(Missing venue id: {d['venue_id']})" if d["venue_id"] else "No venue selected"
        d["race_name"] = d["race_name"] if d["race_name"] else f"(Missing race id: {d['race_name_id']})" if d["race_name_id"] else "No race name selected"
        d["checklist"] = checklist_data
        d["profit"] = calc_profit(
            d.get("decision_type"),
            d.get("odds"),
            d.get("stake"),
            d.get("finished_place"),
            d.get("bet_type"),
        )
        results.append(d)
    return results


def checklist_records_to_df(records, criteria_names):
    rows = []
    for r in records:
        row = {
            "id": r["id"],
            "date_of_race": r.get("date_of_race"),
            "horse_name": r.get("horse_name"),
            "horse_id": r.get("horse_id"),
            "jockey_name": r.get("jockey_name"),
            "trainer_name": r.get("trainer_name"),
            "venue_name": r.get("venue_name"),
            "race_name": r.get("race_name"),
            "distance": r.get("distance"),
            "track_condition": r.get("track_condition"),
            "race_class": r.get("race_class"),
            "pace_scenario": r.get("pace_scenario"),
            "draw_bias_note": r.get("draw_bias_note"),
            "program_number": r.get("program_number"),
            "number_of_horses": r.get("number_of_horses"),
            "bracket_number": r.get("bracket_number"),
            "horse_number": r.get("horse_number"),
            "odds": r.get("odds"),
            "estimated_win_probability_pct": r.get("estimated_win_probability"),
            "fair_odds": r.get("fair_odds"),
            "edge_percent": r.get("edge_percent"),
            "decision_type": r.get("decision_type"),
            "bet_type": r.get("bet_type"),
            "stake": r.get("stake"),
            "finished_place": r.get("finished_place"),
            "profit": r.get("profit"),
            "memo": r.get("memo"),
            "is_locked": r.get("is_locked"),
        }
        for c in criteria_names:
            row[f"criteria__{c}"] = 1 if r.get("checklist", {}).get(c, False) else 0
        rows.append(row)
    return pd.DataFrame(rows)


# =========================
# UI
# =========================
def render_master_page(title, owner_id, getter, adder, updater, deleter, key_name, label):
    st.header(title)
    new_value = st.text_input(label, key=f"{key_name}_input")
    if st.button(f"Add {label}", key=f"add_{key_name}_btn"):
        if not new_value.strip():
            st.error(f"Please enter {label.lower()}.")
        else:
            ok, msg = adder(owner_id, new_value.strip())
            st.success(msg) if ok else st.error(msg)

    st.write(f"### Edit/Delete Registered {label}s")
    items = getter(owner_id)
    if not items:
        st.info(f"No {label.lower()}s registered yet.")
        return

    for item in items:
        display = item[[k for k in item.keys() if k != "id"][0]]
        with st.expander(f"{label}: {display}"):
            edited = st.text_input(
                f"Edit {label}",
                value=display,
                key=f"edit_{key_name}_{item['id']}"
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Update", key=f"update_{key_name}_{item['id']}"):
                    if not edited.strip():
                        st.error(f"Please enter {label.lower()}.")
                    else:
                        ok, msg = updater(item["id"], owner_id, edited.strip())
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            with c2:
                if st.button("Delete", key=f"delete_{key_name}_{item['id']}"):
                    deleter(item["id"], owner_id)
                    st.success(f"{label} deleted.")
                    st.rerun()


def get_name_to_id(items, key):
    return {x[key]: x["id"] for x in items}


# =========================
# App
# =========================
init_db()
st.set_page_config(page_title="Horse Checklist Pro", layout="wide")
st.title("🐎 Horse Checklist Pro")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.display_name = ""
    st.session_state.user_id = None

if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab2:
        st.header("Register")
        reg_username = st.text_input("Username", key="reg_username_unique")
        reg_display = st.text_input("Display Name", key="reg_display_unique")
        reg_password = st.text_input("Password", type="password", key="reg_password_unique")
        reg_invite = st.text_input("Invitation Code", key="reg_invite_unique")
        if st.button("Register", key="register_btn"):
            if not reg_username.strip() or not reg_display.strip() or not reg_password.strip() or not reg_invite.strip():
                st.error("Please fill all fields.")
            else:
                ok, msg = register_user(reg_username.strip(), reg_display.strip(), reg_password, reg_invite.strip())
                st.success(msg) if ok else st.error(msg)

    with tab1:
        st.header("Login")
        log_username = st.text_input("Username", key="log_username_unique")
        log_password = st.text_input("Password", type="password", key="log_password_unique")
        if st.button("Login", key="login_btn"):
            if not log_username.strip() or not log_password.strip():
                st.error("Please fill all fields.")
            else:
                ok, disp_name, user_id = login_user(log_username.strip(), log_password)
                if ok:
                    st.session_state.logged_in = True
                    st.session_state.username = log_username.strip()
                    st.session_state.display_name = disp_name
                    st.session_state.user_id = user_id
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
else:
    owner_id = st.session_state.user_id
    st.sidebar.write(f"Logged in as: {st.session_state.display_name}")

    page = st.sidebar.radio(
        "Menu",
        [
            "Register Horse (Template)",
            "Register Jockey (Template)",
            "Register Trainer (Template)",
            "Register Venue (Template)",
            "Register Race Name (Template)",
            "Register Criteria (Template)",
            "Race Checklist",
            "Checklist Review",
            "Performance Dashboard",
        ],
    )

    if st.sidebar.button("Logout", key="logout_btn"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.display_name = ""
        st.session_state.user_id = None
        st.rerun()

    if page == "Register Horse (Template)":
        render_master_page("Register a Horse Template", owner_id, get_user_horses, add_horse, update_horse, delete_horse, "horse", "Horse Name")

    elif page == "Register Jockey (Template)":
        render_master_page("Register a Jockey Template", owner_id, get_user_jockeys, add_jockey, update_jockey, delete_jockey, "jockey", "Jockey Name")

    elif page == "Register Trainer (Template)":
        render_master_page("Register a Trainer Template", owner_id, get_user_trainers, add_trainer, update_trainer, delete_trainer, "trainer", "Trainer Name")

    elif page == "Register Venue (Template)":
        render_master_page("Register a Venue Template", owner_id, get_user_venues, add_venue, update_venue, delete_venue, "venue", "Venue Name")

    elif page == "Register Race Name (Template)":
        render_master_page("Register a Race Name Template", owner_id, get_user_race_names, add_race_name, update_race_name, delete_race_name, "race_name", "Race Name")

    elif page == "Register Criteria (Template)":
        render_master_page("Register Checklist Criteria", owner_id, get_user_criteria, add_criteria, update_criteria, delete_criteria, "criteria", "Criteria Name")

    elif page == "Race Checklist":
        st.header("Race Checklist")

        horses = get_user_horses(owner_id)
        jockeys = get_user_jockeys(owner_id)
        trainers = get_user_trainers(owner_id)
        venues = get_user_venues(owner_id)
        race_names = get_user_race_names(owner_id)
        criteria = get_user_criteria(owner_id)

        horse_options, horse_ids = get_entity_options(horses, "horse_name")
        jockey_options, jockey_ids = get_entity_options(jockeys, "jockey_name")
        trainer_options, trainer_ids = get_entity_options(trainers, "trainer_name")
        venue_options, venue_ids = get_entity_options(venues, "venue_name")
        race_options, race_ids = get_entity_options(race_names, "race_name")

        c1, c2, c3 = st.columns(3)
        with c1:
            selected_horse_idx = st.selectbox("Horse", range(len(horse_options)), format_func=lambda x: horse_options[x])
            selected_jockey_idx = st.selectbox("Jockey", range(len(jockey_options)), format_func=lambda x: jockey_options[x])
            selected_trainer_idx = st.selectbox("Trainer", range(len(trainer_options)), format_func=lambda x: trainer_options[x])
            selected_venue_idx = st.selectbox("Venue", range(len(venue_options)), format_func=lambda x: venue_options[x])
            selected_race_idx = st.selectbox("Race Name", range(len(race_options)), format_func=lambda x: race_options[x])

        with c2:
            date_of_race = st.date_input("Date of Race", value=date.today())
            distance = st.number_input("Distance (meters)", min_value=0, max_value=5000, value=0, step=100)
            program_number = st.number_input("Program Number", min_value=0, max_value=18, value=0, step=1)
            number_of_horses = st.number_input("Number of Horses", min_value=0, max_value=30, value=0, step=1)
            bracket_number = st.number_input("Bracket Number", min_value=0, max_value=8, value=0, step=1)
            horse_number = st.number_input("Horse Number", min_value=0, max_value=30, value=0, step=1)

        with c3:
            odds = st.number_input("Market Odds", min_value=0.0, max_value=999.9, value=0.0, step=0.1)
            prize = st.number_input("Prize", min_value=0.0, max_value=999999999.0, value=0.0, step=1000.0)
            finished_place = st.text_input("Finished Place")
            track_condition = st.selectbox("Track Condition", ["", "Firm", "Good", "Yielding", "Soft", "Heavy"])
            race_class = st.selectbox("Race Class", ["", "G1", "G2", "G3", "Listed", "Open", "Allowance", "Maiden", "Other"])
            pace_scenario = st.selectbox("Pace Scenario", ["", "Slow", "Average", "Fast", "Unknown"])

        draw_bias_note = st.text_input("Draw Bias Note (optional)")
        memo = st.text_area("Memo")

        st.markdown("### Checklist Criteria")
        checklist_data = {}
        cols = st.columns(3) if criteria else []
        for i, crit in enumerate(criteria):
            with cols[i % 3]:
                checklist_data[crit["criteria_name"]] = st.checkbox(crit["criteria_name"], key=f"crit_{crit['id']}")

        checklist_score = checklist_score_from_dict(checklist_data)
        st.info(f"Checklist Score: {checklist_score}")

        st.markdown("### Decision & Value")
        d1, d2, d3 = st.columns(3)
        with d1:
            estimated_win_probability = st.number_input("Estimated Win Probability (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
            fair_odds = calc_fair_odds(estimated_win_probability) if estimated_win_probability > 0 else None
            st.caption(f"Fair Odds: {fair_odds:.2f}" if fair_odds else "Fair Odds: -")
        with d2:
            implied_probability = calc_implied_probability(odds)
            edge_percent = calc_edge_percent(estimated_win_probability, odds)
            st.caption(f"Implied Probability: {implied_probability*100:.2f}%" if implied_probability else "Implied Probability: -")
            st.caption(f"Edge: {edge_percent:.2f}%" if edge_percent is not None else "Edge: -")
        with d3:
            decision_type = st.radio("Decision Type", ["BET", "NO_BET"], horizontal=True)
            bet_type = st.selectbox("Bet Type", ["WIN", "PLACE", "EACH_WAY", "OTHER"])
            bookmaker = st.text_input("Bookmaker")

        st.markdown("### Staking")
        s1, s2, s3 = st.columns(3)
        with s1:
            bankroll_before = st.number_input("Bankroll Before", min_value=0.0, value=0.0, step=100.0)
        with s2:
            kelly_fraction = calc_kelly_fraction_decimal_odds(estimated_win_probability, odds) if odds > 1 else 0.0
            st.caption(f"Full Kelly Fraction: {kelly_fraction:.4f}")
            suggested_fraction = kelly_fraction * 0.5
            st.caption(f"Suggested Fractional Kelly (0.5x): {suggested_fraction:.4f}")
        with s3:
            suggested_kelly_stake = bankroll_before * suggested_fraction if bankroll_before and suggested_fraction > 0 else 0.0
            stake = st.number_input("Actual Stake", min_value=0.0, value=float(round(suggested_kelly_stake, 2)), step=10.0)
            st.caption(f"Suggested Kelly Stake: {suggested_kelly_stake:.2f}")

        lock_after_save = st.checkbox("Lock record after saving", value=False)

        if st.button("Save Checklist", key="save_checklist_btn"):
            now_str = datetime.now().isoformat(timespec="seconds")
            payload = {
                "owner_id": owner_id,
                "horse_id": horse_ids[selected_horse_idx],
                "jockey_id": jockey_ids[selected_jockey_idx],
                "trainer_id": trainer_ids[selected_trainer_idx],
                "venue_id": venue_ids[selected_venue_idx],
                "race_name_id": race_ids[selected_race_idx],
                "distance": distance if distance > 0 else None,
                "date_of_race": date_of_race.isoformat(),
                "memo": memo.strip(),
                "finished_place": finished_place.strip() or None,
                "checklist": json.dumps(checklist_data) if checklist_data else None,
                "program_number": program_number if program_number > 0 else None,
                "number_of_horses": number_of_horses if number_of_horses > 0 else None,
                "odds": odds if odds > 0 else None,
                "prize": prize if prize > 0 else None,
                "bracket_number": bracket_number if bracket_number > 0 else None,
                "horse_number": horse_number if horse_number > 0 else None,
                "track_condition": track_condition or None,
                "race_class": race_class or None,
                "pace_scenario": pace_scenario or None,
                "draw_bias_note": draw_bias_note.strip() or None,
                "checklist_score": checklist_score,
                "estimated_win_probability": estimated_win_probability if estimated_win_probability > 0 else None,
                "fair_odds": fair_odds,
                "implied_probability": implied_probability,
                "edge_percent": edge_percent,
                "decision_type": decision_type,
                "bet_type": bet_type,
                "bookmaker": bookmaker.strip() or None,
                "stake": stake if decision_type == "BET" and stake > 0 else 0.0,
                "bankroll_before": bankroll_before if bankroll_before > 0 else None,
                "suggested_kelly_fraction": suggested_fraction if suggested_fraction > 0 else 0.0,
                "suggested_kelly_stake": suggested_kelly_stake if suggested_kelly_stake > 0 else 0.0,
                "is_locked": 1 if lock_after_save else 0,
                "created_at": now_str,
                "updated_at": now_str,
            }
            ok, msg = add_checklist_record(payload)
            st.success(msg) if ok else st.error(msg)

        st.markdown("---")
        st.subheader("Batch Import Race Checklists")

        sample_data = pd.DataFrame({
            "horse": ["Sample Horse A", "Sample Horse B"],
            "jockey": ["", ""],
            "trainer": ["", ""],
            "venue": ["Tokyo", "Kyoto"],
            "race_name": ["Demo Race", "Spring Stakes"],
            "distance": [1600, 1800],
            "date_of_race": ["2026-04-01", "2026-04-07"],
            "memo": ["sample", "sample"],
            "odds": [3.2, 12.5],
            "estimated_win_probability": [35, 10],
            "decision_type": ["BET", "NO_BET"],
            "bet_type": ["WIN", "WIN"],
            "stake": [1000, 0],
            "track_condition": ["Good", "Firm"],
            "race_class": ["G3", "Open"],
            "pace_scenario": ["Average", "Fast"],
        })
        template_bytes = io.BytesIO()
        sample_data.to_csv(template_bytes, index=False)
        template_bytes.seek(0)

        st.download_button(
            label="📥 Download CSV Template",
            data=template_bytes,
            file_name="race_checklist_template_improved.csv",
            mime="text/csv",
        )

        uploaded_file = st.file_uploader(
            "Upload CSV or XLSX with at least: horse, date_of_race.",
            type=["csv", "xlsx"]
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.lower().endswith(".csv"):
                    df_import = pd.read_csv(uploaded_file)
                else:
                    df_import = pd.read_excel(uploaded_file)

                df_import.columns = [str(c).strip().lower().replace(" ", "_") for c in df_import.columns]

                horses_map = get_name_to_id(get_user_horses(owner_id), "horse_name")
                jockeys_map = get_name_to_id(get_user_jockeys(owner_id), "jockey_name")
                trainers_map = get_name_to_id(get_user_trainers(owner_id), "trainer_name")
                venues_map = get_name_to_id(get_user_venues(owner_id), "venue_name")
                races_map = get_name_to_id(get_user_race_names(owner_id), "race_name")

                def get_or_add_horse_id(name):
                    if pd.isna(name) or not str(name).strip():
                        return None
                    nm = str(name).strip()
                    if nm in horses_map:
                        return horses_map[nm]
                    add_horse(owner_id, nm)
                    horses_map.update(get_name_to_id(get_user_horses(owner_id), "horse_name"))
                    return horses_map.get(nm)

                def get_or_add_race_id(name):
                    if pd.isna(name) or not str(name).strip():
                        return None
                    nm = str(name).strip()
                    if nm in races_map:
                        return races_map[nm]
                    add_race_name(owner_id, nm)
                    races_map.update(get_name_to_id(get_user_race_names(owner_id), "race_name"))
                    return races_map.get(nm)

                success_count = 0
                failed = []

                for idx, row in df_import.iterrows():
                    try:
                        horse_id = get_or_add_horse_id(row.get("horse"))
                        race_id = get_or_add_race_id(row.get("race_name"))
                        jockey_id = jockeys_map.get(str(row.get("jockey")).strip()) if pd.notna(row.get("jockey")) and str(row.get("jockey")).strip() in jockeys_map else None
                        trainer_id = trainers_map.get(str(row.get("trainer")).strip()) if pd.notna(row.get("trainer")) and str(row.get("trainer")).strip() in trainers_map else None
                        venue_id = venues_map.get(str(row.get("venue")).strip()) if pd.notna(row.get("venue")) and str(row.get("venue")).strip() in venues_map else None

                        est_prob = safe_float(row.get("estimated_win_probability"))
                        imported_odds = safe_float(row.get("odds"))
                        implied_prob = calc_implied_probability(imported_odds)
                        fair = calc_fair_odds(est_prob) if est_prob else None
                        edge = calc_edge_percent(est_prob, imported_odds) if est_prob and imported_odds else None
                        kelly = calc_kelly_fraction_decimal_odds(est_prob, imported_odds) if est_prob and imported_odds else 0.0
                        bankroll_before_import = safe_float(row.get("bankroll_before"))
                        suggested_kelly_stake = (bankroll_before_import or 0) * (kelly * 0.5)

                        payload = {
                            "owner_id": owner_id,
                            "horse_id": horse_id,
                            "jockey_id": jockey_id,
                            "trainer_id": trainer_id,
                            "venue_id": venue_id,
                            "race_name_id": race_id,
                            "distance": safe_int(row.get("distance")),
                            "date_of_race": normalize_date(row.get("date_of_race")),
                            "memo": str(row.get("memo")).strip() if pd.notna(row.get("memo")) else "",
                            "finished_place": str(row.get("finished_place")).strip() if pd.notna(row.get("finished_place")) else None,
                            "checklist": None,
                            "program_number": safe_int(row.get("program_number")),
                            "number_of_horses": safe_int(row.get("number_of_horses")),
                            "odds": imported_odds,
                            "prize": safe_float(row.get("prize")),
                            "bracket_number": safe_int(row.get("bracket_number")),
                            "horse_number": safe_int(row.get("horse_number")),
                            "track_condition": str(row.get("track_condition")).strip() if pd.notna(row.get("track_condition")) else None,
                            "race_class": str(row.get("race_class")).strip() if pd.notna(row.get("race_class")) else None,
                            "pace_scenario": str(row.get("pace_scenario")).strip() if pd.notna(row.get("pace_scenario")) else None,
                            "draw_bias_note": str(row.get("draw_bias_note")).strip() if pd.notna(row.get("draw_bias_note")) else None,
                            "checklist_score": safe_float(row.get("checklist_score")) or 0,
                            "estimated_win_probability": est_prob,
                            "fair_odds": fair,
                            "implied_probability": implied_prob,
                            "edge_percent": edge,
                            "decision_type": str(row.get("decision_type")).strip() if pd.notna(row.get("decision_type")) else "NO_BET",
                            "bet_type": str(row.get("bet_type")).strip() if pd.notna(row.get("bet_type")) else "WIN",
                            "bookmaker": str(row.get("bookmaker")).strip() if pd.notna(row.get("bookmaker")) else None,
                            "stake": safe_float(row.get("stake")) or 0.0,
                            "bankroll_before": bankroll_before_import,
                            "suggested_kelly_fraction": kelly * 0.5,
                            "suggested_kelly_stake": suggested_kelly_stake,
                            "is_locked": 0,
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                        }
                        ok, msg = add_checklist_record(payload)
                        if ok:
                            success_count += 1
                        else:
                            failed.append((idx + 2, msg))
                    except Exception as e:
                        failed.append((idx + 2, str(e)))

                st.success(f"Imported {success_count} rows.")
                if failed:
                    st.error("Failed rows: " + "; ".join([f"Row {r}: {m}" for r, m in failed[:20]]))
            except Exception as e:
                st.error(f"Import error: {e}")

    elif page == "Checklist Review":
        st.header("Checklist Review")

        records = get_user_checklists(owner_id)
        criteria = get_user_criteria(owner_id)
        criteria_names = [c["criteria_name"] for c in criteria]

        horses = get_user_horses(owner_id)
        venues = get_user_venues(owner_id)
        race_names = get_user_race_names(owner_id)

        horse_names = ["All"] + [h["horse_name"] for h in horses]
        venue_names = ["All"] + [v["venue_name"] for v in venues]
        race_name_list = ["All"] + [r["race_name"] for r in race_names]

        st.caption(f"Raw records found for this user: {len(records)}")

        with st.expander("Filters", expanded=True):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                filter_horse = st.selectbox("Horse", horse_names, index=0)
                filter_decision = st.selectbox("Decision", ["All", "BET", "NO_BET"], index=0)
                filter_track = st.selectbox("Track Condition", ["All", "", "Firm", "Good", "Yielding", "Soft", "Heavy"], index=0)
            with f2:
                filter_venue = st.selectbox("Venue", venue_names, index=0)
                filter_bet_type = st.selectbox("Bet Type", ["All", "WIN", "PLACE", "EACH_WAY", "OTHER"], index=0)
                filter_class = st.selectbox("Race Class", ["All", "", "G1", "G2", "G3", "Listed", "Open", "Allowance", "Maiden", "Other"], index=0)
            with f3:
                filter_race = st.selectbox("Race Name", race_name_list, index=0)
                min_edge = st.number_input("Min Edge %", value=-999.0, step=0.1)
                min_odds = st.number_input("Min Odds", value=0.0, step=0.1)
            with f4:
                max_odds = st.number_input("Max Odds", value=999.9, step=0.1)
                lock_only = st.checkbox("Locked only", value=False)
                only_with_result = st.checkbox("Only with result", value=False)

            filter_criteria = st.multiselect("Criteria (must match all)", criteria_names)

        filtered = []
        for r in records:
            if filter_horse != "All" and r["horse_name"] != filter_horse:
                continue
            if filter_venue != "All" and r["venue_name"] != filter_venue:
                continue
            if filter_race != "All" and r["race_name"] != filter_race:
                continue
            if filter_decision != "All" and (r.get("decision_type") or "") != filter_decision:
                continue
            if filter_bet_type != "All" and (r.get("bet_type") or "") != filter_bet_type:
                continue
            if filter_track != "All" and (r.get("track_condition") or "") != filter_track:
                continue
            if filter_class != "All" and (r.get("race_class") or "") != filter_class:
                continue
            if lock_only and not r.get("is_locked"):
                continue
            if only_with_result and not str(r.get("finished_place") or "").strip():
                continue

            odds_val = r.get("odds")
            if odds_val is not None:
                if odds_val < min_odds or odds_val > max_odds:
                    continue
            else:
                if min_odds > 0:
                    continue

            edge = r.get("edge_percent")
            edge_check = edge if edge is not None else -999
            if edge_check < min_edge:
                continue

            if filter_criteria:
                if not all(r["checklist"].get(c, False) for c in filter_criteria):
                    continue

            filtered.append(r)

        st.caption(f"Filtered records shown: {len(filtered)}")

        if not filtered:
            st.info("No records found with current filters.")
        else:
            df = checklist_records_to_df(filtered, criteria_names)
            st.dataframe(df, use_container_width=True, height=450)
            to_csv_download(df, "filtered_checklists.csv")

            st.markdown("### Edit / Lock / Delete")
            selectable = {f"{r['date_of_race']} | {r['horse_name']} | {r['race_name']} | ID {r['id']}": r for r in filtered}
            selected_label = st.selectbox("Select record", list(selectable.keys()))
            entry = selectable[selected_label]

            if entry.get("is_locked"):
                st.warning("This record is locked. You cannot edit or delete it.")
            else:
                horses = get_user_horses(owner_id)
                jockeys = get_user_jockeys(owner_id)
                trainers = get_user_trainers(owner_id)
                venues = get_user_venues(owner_id)
                race_names = get_user_race_names(owner_id)

                horse_options, horse_ids = get_entity_options(horses, "horse_name")
                jockey_options, jockey_ids = get_entity_options(jockeys, "jockey_name")
                trainer_options, trainer_ids = get_entity_options(trainers, "trainer_name")
                venue_options, venue_ids = get_entity_options(venues, "venue_name")
                race_options, race_ids = get_entity_options(race_names, "race_name")

                e1, e2, e3 = st.columns(3)
                with e1:
                    edit_horse_idx = st.selectbox("Horse", range(len(horse_options)), index=idx_or_zero(horse_ids, entry["horse_id"]), format_func=lambda x: horse_options[x], key=f"edit_h_{entry['id']}")
                    edit_jockey_idx = st.selectbox("Jockey", range(len(jockey_options)), index=idx_or_zero(jockey_ids, entry["jockey_id"]), format_func=lambda x: jockey_options[x], key=f"edit_j_{entry['id']}")
                    edit_trainer_idx = st.selectbox("Trainer", range(len(trainer_options)), index=idx_or_zero(trainer_ids, entry["trainer_id"]), format_func=lambda x: trainer_options[x], key=f"edit_t_{entry['id']}")
                with e2:
                    edit_venue_idx = st.selectbox("Venue", range(len(venue_options)), index=idx_or_zero(venue_ids, entry["venue_id"]), format_func=lambda x: venue_options[x], key=f"edit_v_{entry['id']}")
                    edit_race_idx = st.selectbox("Race Name", range(len(race_options)), index=idx_or_zero(race_ids, entry["race_name_id"]), format_func=lambda x: race_options[x], key=f"edit_r_{entry['id']}")
                    default_date = normalize_date(entry["date_of_race"]) or date.today().isoformat()
                    edit_date = st.date_input("Date", value=datetime.fromisoformat(default_date).date(), key=f"edit_d_{entry['id']}")
                    edit_distance = st.number_input("Distance", min_value=0, max_value=5000, value=entry.get("distance") or 0, step=100, key=f"edit_dist_{entry['id']}")
                with e3:
                    edit_odds = st.number_input("Odds", min_value=0.0, max_value=999.9, value=float(entry.get("odds") or 0.0), step=0.1, key=f"edit_odds_{entry['id']}")
                    edit_prob = st.number_input("Estimated Win Probability %", min_value=0.0, max_value=100.0, value=float(entry.get("estimated_win_probability") or 0.0), step=0.1, key=f"edit_prob_{entry['id']}")
                    edit_stake = st.number_input("Stake", min_value=0.0, value=float(entry.get("stake") or 0.0), step=10.0, key=f"edit_stake_{entry['id']}")
                    edit_place = st.text_input("Finished Place", value=entry.get("finished_place") or "", key=f"edit_place_{entry['id']}")

                edit_track = st.selectbox("Track Condition", ["", "Firm", "Good", "Yielding", "Soft", "Heavy"], index=["", "Firm", "Good", "Yielding", "Soft", "Heavy"].index(entry.get("track_condition") or ""), key=f"edit_track_{entry['id']}")
                edit_class = st.selectbox("Race Class", ["", "G1", "G2", "G3", "Listed", "Open", "Allowance", "Maiden", "Other"], index=["", "G1", "G2", "G3", "Listed", "Open", "Allowance", "Maiden", "Other"].index(entry.get("race_class") or ""), key=f"edit_class_{entry['id']}")
                edit_pace = st.selectbox("Pace Scenario", ["", "Slow", "Average", "Fast", "Unknown"], index=["", "Slow", "Average", "Fast", "Unknown"].index(entry.get("pace_scenario") or ""), key=f"edit_pace_{entry['id']}")
                edit_draw_bias_note = st.text_input("Draw Bias Note", value=entry.get("draw_bias_note") or "", key=f"edit_draw_{entry['id']}")
                edit_memo = st.text_area("Memo", value=entry.get("memo") or "", key=f"edit_memo_{entry['id']}")
                edit_decision = st.radio("Decision", ["BET", "NO_BET"], index=0 if entry.get("decision_type") == "BET" else 1, horizontal=True, key=f"edit_dec_{entry['id']}")
                edit_bet_type = st.selectbox("Bet Type", ["WIN", "PLACE", "EACH_WAY", "OTHER"], index=["WIN", "PLACE", "EACH_WAY", "OTHER"].index(entry.get("bet_type") or "WIN"), key=f"edit_bt_{entry['id']}")

                criteria = get_user_criteria(owner_id)
                edit_checklist = {}
                crit_cols = st.columns(3) if criteria else []
                for i, crit in enumerate(criteria):
                    with crit_cols[i % 3]:
                        edit_checklist[crit["criteria_name"]] = st.checkbox(
                            crit["criteria_name"],
                            value=entry["checklist"].get(crit["criteria_name"], False),
                            key=f"edit_crit_{entry['id']}_{crit['id']}"
                        )

                u1, u2, u3 = st.columns(3)
                with u1:
                    if st.button("Update Record", key=f"upd_{entry['id']}"):
                        fair_odds = calc_fair_odds(edit_prob) if edit_prob > 0 else None
                        implied = calc_implied_probability(edit_odds)
                        edge = calc_edge_percent(edit_prob, edit_odds)
                        kelly = calc_kelly_fraction_decimal_odds(edit_prob, edit_odds)
                        payload = {
                            "horse_id": horse_ids[edit_horse_idx],
                            "jockey_id": jockey_ids[edit_jockey_idx],
                            "trainer_id": trainer_ids[edit_trainer_idx],
                            "venue_id": venue_ids[edit_venue_idx],
                            "race_name_id": race_ids[edit_race_idx],
                            "distance": edit_distance if edit_distance > 0 else None,
                            "date_of_race": edit_date.isoformat(),
                            "memo": edit_memo.strip(),
                            "finished_place": edit_place.strip() or None,
                            "checklist": json.dumps(edit_checklist),
                            "odds": edit_odds if edit_odds > 0 else None,
                            "track_condition": edit_track or None,
                            "race_class": edit_class or None,
                            "pace_scenario": edit_pace or None,
                            "draw_bias_note": edit_draw_bias_note.strip() or None,
                            "checklist_score": checklist_score_from_dict(edit_checklist),
                            "estimated_win_probability": edit_prob if edit_prob > 0 else None,
                            "fair_odds": fair_odds,
                            "implied_probability": implied,
                            "edge_percent": edge,
                            "decision_type": edit_decision,
                            "bet_type": edit_bet_type,
                            "stake": edit_stake if edit_decision == "BET" else 0.0,
                            "suggested_kelly_fraction": kelly * 0.5,
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                        }
                        ok, msg = update_checklist_record(entry["id"], owner_id, payload)
                        st.success(msg) if ok else st.error(msg)
                        if ok:
                            st.rerun()
                with u2:
                    if st.button("Lock Record", key=f"lock_{entry['id']}"):
                        lock_checklist(entry["id"], owner_id)
                        st.success("Record locked.")
                        st.rerun()
                with u3:
                    if st.button("Delete Record", key=f"del_{entry['id']}"):
                        delete_checklist(entry["id"], owner_id)
                        st.success("Record deleted.")
                        st.rerun()

    elif page == "Performance Dashboard":
        st.header("Performance Dashboard")

        records = get_user_checklists(owner_id)
        criteria = get_user_criteria(owner_id)
        criteria_names = [c["criteria_name"] for c in criteria]

        if not records:
            st.info("No records yet.")
        else:
            df = checklist_records_to_df(records, criteria_names)
            bet_df = df[df["decision_type"] == "BET"].copy()

            if len(bet_df) == 0:
                st.info("No BET records yet.")
            else:
                bet_df["date_of_race"] = pd.to_datetime(bet_df["date_of_race"], errors="coerce")
                bet_df = bet_df.sort_values("date_of_race")
                bet_df["cum_profit"] = bet_df["profit"].fillna(0).cumsum()

                total_bets = len(bet_df)
                total_stake = bet_df["stake"].fillna(0).sum()
                total_profit = bet_df["profit"].fillna(0).sum()
                roi = (total_profit / total_stake * 100) if total_stake > 0 else 0

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Bets", f"{total_bets}")
                c2.metric("Total Stake", f"{total_stake:,.1f}")
                c3.metric("Total Profit", f"{total_profit:,.1f}")
                c4.metric("ROI %", f"{roi:.2f}")

                st.markdown("### Profit Curve")
                curve_df = bet_df[["date_of_race", "cum_profit"]].copy()
                st.line_chart(curve_df.set_index("date_of_race"))

                st.markdown("### Export")
                to_csv_download(df, "all_checklists_analysis.csv")
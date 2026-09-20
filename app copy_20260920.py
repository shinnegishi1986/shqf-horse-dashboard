import streamlit as st
import sqlite3
import os
import bcrypt
import json
from datetime import date, datetime
import pandas as pd
import io

# IMPORTANT:
# For Streamlit Community Cloud, data written to the local disk can be reset
# after redeploy/restart. Use persistent storage for production data if needed.
DB_PATH = "data/horse_checklist_app.db"

st.set_page_config(page_title="Horse Checklist App", layout="centered")


# -------------------------------------------------
# Database
# -------------------------------------------------
def get_db_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invitation_codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS horses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_name TEXT NOT NULL,
            UNIQUE(owner_id, horse_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS horse_owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_owner_name TEXT NOT NULL,
            UNIQUE(owner_id, horse_owner_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jockeys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            jockey_name TEXT NOT NULL,
            UNIQUE(owner_id, jockey_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trainers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            trainer_name TEXT NOT NULL,
            UNIQUE(owner_id, trainer_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS breeding_farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            breeding_farm_name TEXT NOT NULL,
            UNIQUE(owner_id, breeding_farm_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stallions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            stallion_name TEXT NOT NULL,
            UNIQUE(owner_id, stallion_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            criteria_name TEXT NOT NULL,
            UNIQUE(owner_id, criteria_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            venue_name TEXT NOT NULL,
            UNIQUE(owner_id, venue_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS race_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            race_name TEXT NOT NULL,
            UNIQUE(owner_id, race_name),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            horse_id INTEGER,
            horse_owner_id INTEGER,
            jockey_id INTEGER,
            previous_jockey_id INTEGER,
            trainer_id INTEGER,
            breeding_farm_id INTEGER,
            stallion_id INTEGER,
            broodmare_sire_id INTEGER,
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
            horse_weight REAL,
            FOREIGN KEY(owner_id) REFERENCES users(id),
            FOREIGN KEY(horse_id) REFERENCES horses(id),
            FOREIGN KEY(horse_owner_id) REFERENCES horse_owners(id),
            FOREIGN KEY(jockey_id) REFERENCES jockeys(id),
            FOREIGN KEY(previous_jockey_id) REFERENCES jockeys(id),
            FOREIGN KEY(trainer_id) REFERENCES trainers(id),
            FOREIGN KEY(breeding_farm_id) REFERENCES breeding_farms(id),
            FOREIGN KEY(stallion_id) REFERENCES stallions(id),
            FOREIGN KEY(broodmare_sire_id) REFERENCES stallions(id),
            FOREIGN KEY(venue_id) REFERENCES venues(id),
            FOREIGN KEY(race_name_id) REFERENCES race_names(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_filters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filter_data TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_id, title),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)

    cursor.execute("PRAGMA table_info(checklists)")
    existing_columns = {row["name"] for row in cursor.fetchall()}

    required_columns = {
        "horse_owner_id": "INTEGER",
        "jockey_id": "INTEGER",
        "previous_jockey_id": "INTEGER",
        "trainer_id": "INTEGER",
        "breeding_farm_id": "INTEGER",
        "stallion_id": "INTEGER",
        "broodmare_sire_id": "INTEGER",
        "venue_id": "INTEGER",
        "race_name_id": "INTEGER",
        "distance": "INTEGER",
        "date_of_race": "TEXT",
        "memo": "TEXT",
        "finished_place": "TEXT",
        "checklist": "TEXT",
        "program_number": "INTEGER",
        "number_of_horses": "INTEGER",
        "odds": "REAL",
        "prize": "REAL",
        "bracket_number": "INTEGER",
        "horse_number": "INTEGER",
        "horse_weight": "REAL",
    }

    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE checklists ADD COLUMN {column_name} {column_type}"
            )

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS unique_owner_horse_date
        ON checklists (owner_id, horse_id, date_of_race)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_checklists_owner_date
        ON checklists (owner_id, date_of_race DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_saved_filters_owner
        ON saved_filters (owner_id, created_at DESC)
    """)

    conn.commit()
    conn.close()


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value).strip()


def safe_json_loads(value):
    if not value:
        return {}

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def parse_race_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except (ValueError, TypeError):
            continue

    return None


def normalize_date(date_val):
    if pd.isna(date_val) or not date_val:
        return None

    if isinstance(date_val, (datetime, pd.Timestamp)):
        return date_val.date().strftime("%Y-%m-%d")

    if isinstance(date_val, date):
        return date_val.strftime("%Y-%m-%d")

    date_str = str(date_val).strip()

    if " " in date_str:
        date_str = date_str.split(" ")[0]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        if date_str.isdigit():
            excel_date = pd.to_datetime(
                float(date_str),
                unit="d",
                origin="1899-12-30",
            )
            return excel_date.strftime("%Y-%m-%d")
    except Exception:
        pass

    return date_str if date_str else None


def to_optional_int(value):
    try:
        if value is None or pd.isna(value):
            return None

        value = int(float(value))
        return value if value > 0 else None
    except (ValueError, TypeError):
        return None


def to_optional_float(value):
    try:
        if value is None or pd.isna(value):
            return None

        value = float(value)
        return value if value > 0 else None
    except (ValueError, TypeError):
        return None


def parse_optional_int(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_optional_float(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_boolean(value):
    if isinstance(value, bool):
        return value

    if value is None or pd.isna(value):
        return False

    normalized = clean_text(value).lower()

    return normalized in {
        "1",
        "true",
        "t",
        "yes",
        "y",
        "on",
        "checked",
        "✓",
    }


def make_options(items, label_key):
    labels = ["(No selection)"] + [item[label_key] for item in items]
    ids = [None] + [item["id"] for item in items]
    return labels, ids


def get_selected_id(options_ids, selected_index):
    if selected_index < 0 or selected_index >= len(options_ids):
        return None
    return options_ids[selected_index]


def format_yen(value):
    if value is None:
        return "N/A"

    return f"¥{value:,.0f}"


def get_paginated_items(items, page_number, page_size):
    if page_size <= 0:
        return items

    start_index = (page_number - 1) * page_size
    end_index = start_index + page_size

    return items[start_index:end_index]


# -------------------------------------------------
# Saved Filter / First and Second Filter Helpers
# -------------------------------------------------
def saved_filter_key(owner_id, key_name):
    return f"saved_filter_{owner_id}_{key_name}"


def filter_selectbox_key(owner_id, field_name):
    return saved_filter_key(owner_id, f"select_{field_name}")


def filter_load_version_key(owner_id):
    return saved_filter_key(owner_id, "load_version")


def filter_widget_load_version_key(owner_id, field_name):
    return saved_filter_key(owner_id, f"widget_version_{field_name}")


def second_filter_key(owner_id, key_name):
    return f"second_filter_{owner_id}_{key_name}"


def second_filter_selectbox_key(owner_id, field_name):
    return second_filter_key(owner_id, f"select_{field_name}")


def second_filter_load_version_key(owner_id):
    return second_filter_key(owner_id, "load_version")


def second_filter_widget_load_version_key(owner_id, field_name):
    return second_filter_key(owner_id, f"widget_version_{field_name}")


def get_filter_defaults():
    return {
        "horse_id": None,
        "horse_owner_id": None,
        "jockey_id": None,
        "previous_jockey_id": None,
        "trainer_id": None,
        "breeding_farm_id": None,
        "stallion_id": None,
        "broodmare_sire_id": None,
        "venue_ids": [],
        "race_name_id": None,
        "memo_keyword": "",
        "program_number": 0,
        "number_of_horses": 0,
        "odds_from": 0.0,
        "odds_to": 999.9,
        "prize_from": 0.0,
        "prize_to": 1000000000.0,
        "criteria": [],
        "criteria_mode": "AND",
        "distance_from": 0,
        "distance_to": 5000,
        "date_from": None,
        "date_to": None,
        "places": [],
        "exclude_places": [],
        "enable_bracket_filter": False,
        "bracket_from": 1,
        "bracket_to": 8,
        "enable_horse_filter": False,
        "horse_from": 1,
        "horse_to": 18,
        "enable_weight_filter": False,
        "weight_from": 0.0,
        "weight_to": 999.9,
        "page_size": 50,
        "page_number": 1,
    }


def initialize_filter_defaults(owner_id):
    defaults = get_filter_defaults()
    defaults.update(
        {
            "new_title": "",
            "active_filter_title": "",
            "load_version": 0,
        }
    )

    for key_name, default_value in defaults.items():
        state_key = saved_filter_key(owner_id, key_name)

        if state_key not in st.session_state:
            st.session_state[state_key] = default_value


def initialize_second_filter_defaults(owner_id):
    defaults = get_filter_defaults()
    defaults.update(
        {
            "enabled": False,
            "load_version": 0,
        }
    )

    for key_name, default_value in defaults.items():
        state_key = second_filter_key(owner_id, key_name)

        if state_key not in st.session_state:
            st.session_state[state_key] = default_value


def reset_filter_values(owner_id):
    defaults = get_filter_defaults()
    defaults["active_filter_title"] = ""

    selectbox_fields = [
        "horse_id",
        "horse_owner_id",
        "jockey_id",
        "previous_jockey_id",
        "trainer_id",
        "breeding_farm_id",
        "stallion_id",
        "broodmare_sire_id",
        "race_name_id",
    ]

    for key_name, default_value in defaults.items():
        st.session_state[saved_filter_key(owner_id, key_name)] = default_value

    for field_name in selectbox_fields:
        st.session_state[filter_selectbox_key(owner_id, field_name)] = None
        st.session_state[filter_widget_load_version_key(owner_id, field_name)] = (
            st.session_state[filter_load_version_key(owner_id)]
        )


def reset_second_filter_values(owner_id):
    defaults = get_filter_defaults()

    selectbox_fields = [
        "horse_id",
        "horse_owner_id",
        "jockey_id",
        "previous_jockey_id",
        "trainer_id",
        "breeding_farm_id",
        "stallion_id",
        "broodmare_sire_id",
        "race_name_id",
    ]

    for key_name, default_value in defaults.items():
        st.session_state[second_filter_key(owner_id, key_name)] = default_value

    for field_name in selectbox_fields:
        st.session_state[
            second_filter_selectbox_key(owner_id, field_name)
        ] = None
        st.session_state[
            second_filter_widget_load_version_key(owner_id, field_name)
        ] = st.session_state[second_filter_load_version_key(owner_id)]


def render_filter_selectbox(
    label,
    owner_id,
    field_name,
    option_ids,
    option_labels,
):
    widget_key = filter_selectbox_key(owner_id, field_name)
    filter_state_key = saved_filter_key(owner_id, field_name)
    load_version = st.session_state[filter_load_version_key(owner_id)]
    widget_version_key = filter_widget_load_version_key(owner_id, field_name)

    if st.session_state.get(widget_version_key) != load_version:
        loaded_value = st.session_state.get(filter_state_key)

        st.session_state[widget_key] = (
            loaded_value if loaded_value in option_ids else None
        )
        st.session_state[widget_version_key] = load_version

    if widget_key not in st.session_state:
        initial_value = st.session_state.get(filter_state_key)
        st.session_state[widget_key] = (
            initial_value if initial_value in option_ids else None
        )
        st.session_state[widget_version_key] = load_version

    selected_id = st.selectbox(
        label,
        option_ids,
        format_func=lambda selected_option_id: option_labels[
            option_ids.index(selected_option_id)
        ],
        key=widget_key,
    )

    st.session_state[filter_state_key] = selected_id

    return selected_id


def render_second_filter_selectbox(
    label,
    owner_id,
    field_name,
    option_ids,
    option_labels,
):
    widget_key = second_filter_selectbox_key(owner_id, field_name)
    filter_state_key = second_filter_key(owner_id, field_name)
    load_version = st.session_state[second_filter_load_version_key(owner_id)]
    widget_version_key = second_filter_widget_load_version_key(
        owner_id,
        field_name,
    )

    if st.session_state.get(widget_version_key) != load_version:
        loaded_value = st.session_state.get(filter_state_key)

        st.session_state[widget_key] = (
            loaded_value if loaded_value in option_ids else None
        )
        st.session_state[widget_version_key] = load_version

    if widget_key not in st.session_state:
        initial_value = st.session_state.get(filter_state_key)
        st.session_state[widget_key] = (
            initial_value if initial_value in option_ids else None
        )
        st.session_state[widget_version_key] = load_version

    selected_id = st.selectbox(
        label,
        option_ids,
        format_func=lambda selected_option_id: option_labels[
            option_ids.index(selected_option_id)
        ],
        key=widget_key,
    )

    st.session_state[filter_state_key] = selected_id

    return selected_id


def checklist_to_export_rows(checklists, criteria_items=None):
    criteria_names = []

    if criteria_items:
        criteria_names = [
            criterion["criteria_name"]
            for criterion in criteria_items
        ]

    rows = []

    for entry in checklists:
        checklist_map = entry.get("checklist") or {}

        checked_criteria = [
            criterion
            for criterion, checked in checklist_map.items()
            if checked
        ]

        row = {
            "id": entry.get("id"),
            "horse_name": entry.get("horse_name", ""),
            "horse_owner_name": entry.get("horse_owner_name", ""),
            "jockey_name": entry.get("jockey_name", ""),
            "previous_jockey_name": entry.get("previous_jockey_name", ""),
            "trainer_name": entry.get("trainer_name", ""),
            "breeding_farm_name": entry.get("breeding_farm_name", ""),
            "stallion_name": entry.get("stallion_name", ""),
            "broodmare_sire_name": entry.get("broodmare_sire_name", ""),
            "venue_name": entry.get("venue_name", ""),
            "race_name": entry.get("race_name", ""),
            "distance": entry.get("distance"),
            "date_of_race": entry.get("date_of_race", ""),
            "memo": entry.get("memo", ""),
            "finished_place": entry.get("finished_place", ""),
            "program_number": entry.get("program_number"),
            "number_of_horses": entry.get("number_of_horses"),
            "odds": entry.get("odds"),
            "prize": entry.get("prize"),
            "bracket_number": entry.get("bracket_number"),
            "horse_number": entry.get("horse_number"),
            "horse_weight": entry.get("horse_weight"),
            "checked_criteria": " | ".join(checked_criteria),
        }

        for criterion_name in criteria_names:
            row[f"criteria__{criterion_name}"] = (
                1 if checklist_map.get(criterion_name, False) else 0
            )

        rows.append(row)

    return rows


def build_csv_download_bytes(
    filtered_checklists,
    criteria_items=None,
    encoding="utf-8-sig",
):
    export_rows = checklist_to_export_rows(
        filtered_checklists,
        criteria_items,
    )
    df = pd.DataFrame(export_rows)

    if df.empty:
        columns = [
            "id",
            "horse_name",
            "horse_owner_name",
            "jockey_name",
            "previous_jockey_name",
            "trainer_name",
            "breeding_farm_name",
            "stallion_name",
            "broodmare_sire_name",
            "venue_name",
            "race_name",
            "distance",
            "date_of_race",
            "memo",
            "finished_place",
            "program_number",
            "number_of_horses",
            "odds",
            "prize",
            "bracket_number",
            "horse_number",
            "horse_weight",
            "checked_criteria",
        ]

        if criteria_items:
            columns.extend(
                f"criteria__{criterion['criteria_name']}"
                for criterion in criteria_items
            )

        df = pd.DataFrame(columns=columns)

    return df.to_csv(index=False).encode(encoding, errors="replace")


def build_import_template_bytes(criteria_items):
    columns = [
        "id",
        "horse_name",
        "horse_owner_name",
        "jockey_name",
        "previous_jockey_name",
        "trainer_name",
        "breeding_farm_name",
        "stallion_name",
        "broodmare_sire_name",
        "venue_name",
        "race_name",
        "distance",
        "date_of_race",
        "memo",
        "finished_place",
        "program_number",
        "number_of_horses",
        "odds",
        "prize",
        "bracket_number",
        "horse_number",
        "horse_weight",
        "checked_criteria",
    ]

    criteria_columns = [
        f"criteria__{criterion['criteria_name']}"
        for criterion in criteria_items
    ]

    columns.extend(criteria_columns)

    sample_row = {
        "id": "",
        "horse_name": "Sample Horse A",
        "horse_owner_name": "Sample Horse Owner",
        "jockey_name": "Sample Jockey",
        "previous_jockey_name": "",
        "trainer_name": "Sample Trainer",
        "breeding_farm_name": "",
        "stallion_name": "Sample Stallion",
        "broodmare_sire_name": "",
        "venue_name": "東京",
        "race_name": "Sample Race",
        "distance": 1600,
        "date_of_race": "2025-04-01",
        "memo": "Sample memo",
        "finished_place": "",
        "program_number": 11,
        "number_of_horses": 18,
        "odds": 5.8,
        "prize": 10000000,
        "bracket_number": 3,
        "horse_number": 5,
        "horse_weight": 480,
        "checked_criteria": "",
    }

    for criterion_column in criteria_columns:
        sample_row[criterion_column] = 0

    if criteria_columns:
        sample_row[criteria_columns[0]] = 1

    sample_df = pd.DataFrame([sample_row], columns=columns)

    return sample_df.to_csv(index=False).encode("utf-8-sig")


# -------------------------------------------------
# Authentication
# -------------------------------------------------
def register_user(username, display_name, password, invitation_code):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return False, "Username already exists."

        cursor.execute(
            "SELECT used FROM invitation_codes WHERE code = ?",
            (invitation_code,),
        )
        code_row = cursor.fetchone()

        if not code_row:
            return False, "Invalid invitation code."

        if code_row["used"]:
            return False, "Invitation code has already been used."

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        cursor.execute(
            """
            INSERT INTO users (username, display_name, password)
            VALUES (?, ?, ?)
            """,
            (username, display_name, hashed_password),
        )

        cursor.execute(
            "UPDATE invitation_codes SET used = 1 WHERE code = ?",
            (invitation_code,),
        )

        conn.commit()
        return True, "Registration successful!"

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Registration error: {error}"

    finally:
        conn.close()


def login_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id, display_name, password FROM users WHERE username = ?",
            (username,),
        )
        user = cursor.fetchone()

        if user and bcrypt.checkpw(
            password.encode("utf-8"),
            user["password"].encode("utf-8"),
        ):
            return True, user["display_name"], user["id"]

        return False, None, None

    finally:
        conn.close()


def change_user_password(owner_id, current_password, new_password):
    if not current_password:
        return False, "Please enter your current password."

    if not new_password:
        return False, "Please enter a new password."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT password FROM users WHERE id = ?",
            (owner_id,),
        )
        user = cursor.fetchone()

        if not user:
            return False, "User account was not found."

        if not bcrypt.checkpw(
            current_password.encode("utf-8"),
            user["password"].encode("utf-8"),
        ):
            return False, "Your current password is incorrect."

        if bcrypt.checkpw(
            new_password.encode("utf-8"),
            user["password"].encode("utf-8"),
        ):
            return False, "Your new password must be different from your current password."

        new_hashed_password = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        cursor.execute(
            """
            UPDATE users
            SET password = ?
            WHERE id = ?
            """,
            (new_hashed_password, owner_id),
        )

        conn.commit()
        return True, "Password changed successfully."

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Password change error: {error}"

    finally:
        conn.close()


def add_invitation_code(code):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO invitation_codes (code, used) VALUES (?, 0)",
            (code,),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


# -------------------------------------------------
# Saved filter database functions
# -------------------------------------------------
def get_saved_filters(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id, title, filter_data, created_at
            FROM saved_filters
            WHERE owner_id = ?
            ORDER BY title COLLATE NOCASE, id DESC
            """,
            (owner_id,),
        )

        saved_filters = []

        for row in cursor.fetchall():
            saved_filters.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "filter_data": safe_json_loads(row["filter_data"]),
                    "created_at": row["created_at"],
                }
            )

        return saved_filters

    finally:
        conn.close()


def save_filter(owner_id, title, filter_data):
    title = clean_text(title)

    if not title:
        return False, "Please enter a title for the saved filter."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO saved_filters (owner_id, title, filter_data)
            VALUES (?, ?, ?)
            """,
            (
                owner_id,
                title,
                json.dumps(filter_data, ensure_ascii=False),
            ),
        )
        conn.commit()
        return True, "Filter saved!"

    except sqlite3.IntegrityError:
        return False, "A saved filter with this title already exists."

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"

    finally:
        conn.close()


def delete_saved_filter(saved_filter_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM saved_filters
            WHERE id = ? AND owner_id = ?
            """,
            (saved_filter_id, owner_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return False, "Saved filter was not found."

        return True, "Saved filter deleted!"

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"

    finally:
        conn.close()


def build_saved_filters_backup_bytes(owner_id):
    saved_filters = get_saved_filters(owner_id)

    backup_data = {
        "backup_type": "horse_checklist_saved_filters",
        "backup_version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "filters": [
            {
                "title": saved_filter["title"],
                "filter_data": saved_filter["filter_data"],
                "created_at": saved_filter["created_at"],
            }
            for saved_filter in saved_filters
        ],
    }

    return json.dumps(
        backup_data,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def import_saved_filters_backup(owner_id, uploaded_file):
    try:
        file_content = uploaded_file.getvalue().decode("utf-8-sig")
        backup_data = json.loads(file_content)
    except UnicodeDecodeError:
        return False, "The backup file must be UTF-8 encoded JSON.", 0, 0
    except json.JSONDecodeError:
        return False, "Invalid backup file. Please upload a JSON filter backup.", 0, 0

    if not isinstance(backup_data, dict):
        return False, "Invalid backup file format.", 0, 0

    if backup_data.get("backup_type") != "horse_checklist_saved_filters":
        return False, "This file is not a saved filters backup.", 0, 0

    filters = backup_data.get("filters")

    if not isinstance(filters, list):
        return False, "Invalid backup file: filters list is missing.", 0, 0

    conn = get_db_connection()
    cursor = conn.cursor()

    imported_count = 0
    skipped_count = 0

    try:
        for item in filters:
            if not isinstance(item, dict):
                skipped_count += 1
                continue

            title = clean_text(item.get("title"))
            filter_data = item.get("filter_data")

            if not title or not isinstance(filter_data, dict):
                skipped_count += 1
                continue

            cursor.execute(
                """
                SELECT id
                FROM saved_filters
                WHERE owner_id = ? AND title = ?
                """,
                (owner_id, title),
            )

            if cursor.fetchone():
                skipped_count += 1
                continue

            created_at = clean_text(item.get("created_at"))

            if created_at:
                cursor.execute(
                    """
                    INSERT INTO saved_filters (
                        owner_id,
                        title,
                        filter_data,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        owner_id,
                        title,
                        json.dumps(filter_data, ensure_ascii=False),
                        created_at,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO saved_filters (
                        owner_id,
                        title,
                        filter_data
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        owner_id,
                        title,
                        json.dumps(filter_data, ensure_ascii=False),
                    ),
                )

            imported_count += 1

        conn.commit()

        return (
            True,
            "Saved filters import completed.",
            imported_count,
            skipped_count,
        )

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}", imported_count, skipped_count

    finally:
        conn.close()


def collect_current_filter_data(owner_id):
    def get_value(key, default=None):
        return st.session_state.get(saved_filter_key(owner_id, key), default)

    date_from = get_value("date_from")
    date_to = get_value("date_to")

    return {
        "horse_id": get_value("horse_id", None),
        "horse_owner_id": get_value("horse_owner_id", None),
        "jockey_id": get_value("jockey_id", None),
        "previous_jockey_id": get_value("previous_jockey_id", None),
        "trainer_id": get_value("trainer_id", None),
        "breeding_farm_id": get_value("breeding_farm_id", None),
        "stallion_id": get_value("stallion_id", None),
        "broodmare_sire_id": get_value("broodmare_sire_id", None),
        "venue_ids": get_value("venue_ids", []),
        "race_name_id": get_value("race_name_id", None),
        "memo_keyword": get_value("memo_keyword", ""),
        "program_number": get_value("program_number", 0),
        "number_of_horses": get_value("number_of_horses", 0),
        "odds_from": get_value("odds_from", 0.0),
        "odds_to": get_value("odds_to", 999.9),
        "prize_from": get_value("prize_from", 0.0),
        "prize_to": get_value("prize_to", 1000000000.0),
        "criteria_filters": get_value("criteria", []),
        "criteria_mode": get_value("criteria_mode", "AND"),
        "distance_from": get_value("distance_from", 0),
        "distance_to": get_value("distance_to", 5000),
        "date_from": date_from.isoformat() if isinstance(date_from, date) else None,
        "date_to": date_to.isoformat() if isinstance(date_to, date) else None,
        "finished_places": get_value("places", []),
        "exclude_finished_places": get_value("exclude_places", []),
        "enable_bracket_filter": get_value("enable_bracket_filter", False),
        "bracket_from": get_value("bracket_from", 1),
        "bracket_to": get_value("bracket_to", 8),
        "enable_horse_filter": get_value("enable_horse_filter", False),
        "horse_from": get_value("horse_from", 1),
        "horse_to": get_value("horse_to", 18),
        "enable_weight_filter": get_value("enable_weight_filter", False),
        "weight_from": get_value("weight_from", 0.0),
        "weight_to": get_value("weight_to", 999.9),
    }


def apply_saved_filter_to_session(owner_id, filter_data, filter_title=""):
    reset_filter_values(owner_id)

    def set_value(key, value):
        st.session_state[saved_filter_key(owner_id, key)] = value

    date_from = parse_race_date(filter_data.get("date_from"))
    date_to = parse_race_date(filter_data.get("date_to"))

    saved_venue_ids = filter_data.get("venue_ids")

    if not isinstance(saved_venue_ids, list):
        legacy_venue_id = filter_data.get("venue_id")
        saved_venue_ids = [legacy_venue_id] if legacy_venue_id is not None else []

    set_value("horse_id", filter_data.get("horse_id"))
    set_value("horse_owner_id", filter_data.get("horse_owner_id"))
    set_value("jockey_id", filter_data.get("jockey_id"))
    set_value("previous_jockey_id", filter_data.get("previous_jockey_id"))
    set_value("trainer_id", filter_data.get("trainer_id"))
    set_value("breeding_farm_id", filter_data.get("breeding_farm_id"))
    set_value("stallion_id", filter_data.get("stallion_id"))
    set_value("broodmare_sire_id", filter_data.get("broodmare_sire_id"))
    set_value("venue_ids", saved_venue_ids)
    set_value("race_name_id", filter_data.get("race_name_id"))
    set_value("memo_keyword", filter_data.get("memo_keyword", ""))
    set_value("program_number", int(filter_data.get("program_number", 0) or 0))
    set_value(
        "number_of_horses",
        int(filter_data.get("number_of_horses", 0) or 0),
    )
    set_value("odds_from", float(filter_data.get("odds_from", 0.0) or 0.0))
    set_value("odds_to", float(filter_data.get("odds_to", 999.9) or 999.9))
    set_value("prize_from", float(filter_data.get("prize_from", 0.0) or 0.0))
    set_value(
        "prize_to",
        float(filter_data.get("prize_to", 1000000000.0) or 1000000000.0),
    )
    set_value("criteria", filter_data.get("criteria_filters", []) or [])
    set_value("criteria_mode", filter_data.get("criteria_mode", "AND"))
    set_value("distance_from", int(filter_data.get("distance_from", 0) or 0))
    set_value("distance_to", int(filter_data.get("distance_to", 5000) or 5000))
    set_value("date_from", date_from)
    set_value("date_to", date_to)
    set_value("places", filter_data.get("finished_places", []) or [])
    set_value(
        "exclude_places",
        filter_data.get("exclude_finished_places", []) or [],
    )
    set_value(
        "enable_bracket_filter",
        bool(filter_data.get("enable_bracket_filter", False)),
    )
    set_value("bracket_from", int(filter_data.get("bracket_from", 1) or 1))
    set_value("bracket_to", int(filter_data.get("bracket_to", 8) or 8))
    set_value(
        "enable_horse_filter",
        bool(filter_data.get("enable_horse_filter", False)),
    )
    set_value("horse_from", int(filter_data.get("horse_from", 1) or 1))
    set_value("horse_to", int(filter_data.get("horse_to", 18) or 18))
    set_value(
        "enable_weight_filter",
        bool(filter_data.get("enable_weight_filter", False)),
    )
    set_value("weight_from", float(filter_data.get("weight_from", 0.0) or 0.0))
    set_value("weight_to", float(filter_data.get("weight_to", 999.9) or 999.9))
    set_value("active_filter_title", clean_text(filter_title))

    st.session_state[filter_load_version_key(owner_id)] += 1


# -------------------------------------------------
# Template table helpers
# -------------------------------------------------
TEMPLATE_CONFIG = {
    "horse": ("horses", "horse_name"),
    "horse_owner": ("horse_owners", "horse_owner_name"),
    "jockey": ("jockeys", "jockey_name"),
    "trainer": ("trainers", "trainer_name"),
    "breeding_farm": ("breeding_farms", "breeding_farm_name"),
    "stallion": ("stallions", "stallion_name"),
    "venue": ("venues", "venue_name"),
    "race_name": ("race_names", "race_name"),
    "criteria": ("criteria", "criteria_name"),
}


def get_template_items(template_type, owner_id):
    table_name, name_column = TEMPLATE_CONFIG[template_type]

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            SELECT id, {name_column}
            FROM {table_name}
            WHERE owner_id = ?
            ORDER BY {name_column} COLLATE NOCASE
            """,
            (owner_id,),
        )

        return [
            {"id": row["id"], name_column: row[name_column]}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def add_template_item(template_type, owner_id, value):
    table_name, name_column = TEMPLATE_CONFIG[template_type]
    value = clean_text(value)

    if not value:
        return False, "Please enter a name."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            INSERT INTO {table_name} (owner_id, {name_column})
            VALUES (?, ?)
            """,
            (owner_id, value),
        )
        conn.commit()
        return True, "Saved!"
    except sqlite3.IntegrityError:
        return False, "This name is already registered."
    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"
    finally:
        conn.close()


def update_template_item(template_type, item_id, owner_id, new_value):
    table_name, name_column = TEMPLATE_CONFIG[template_type]
    new_value = clean_text(new_value)

    if not new_value:
        return False, "Please enter a name."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            SELECT id
            FROM {table_name}
            WHERE owner_id = ? AND {name_column} = ? AND id != ?
            """,
            (owner_id, new_value, item_id),
        )

        if cursor.fetchone():
            return False, "Another item with the same name already exists."

        cursor.execute(
            f"""
            UPDATE {table_name}
            SET {name_column} = ?
            WHERE id = ? AND owner_id = ?
            """,
            (new_value, item_id, owner_id),
        )

        conn.commit()
        return True, "Updated!"

    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"

    finally:
        conn.close()


def delete_template_item(template_type, item_id, owner_id):
    table_name, _ = TEMPLATE_CONFIG[template_type]

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"DELETE FROM {table_name} WHERE id = ? AND owner_id = ?",
            (item_id, owner_id),
        )
        conn.commit()
        return True, "Deleted!"
    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"
    finally:
        conn.close()


def get_user_horses(owner_id):
    return get_template_items("horse", owner_id)


def get_user_horse_owners(owner_id):
    return get_template_items("horse_owner", owner_id)


def get_user_jockeys(owner_id):
    return get_template_items("jockey", owner_id)


def get_user_trainers(owner_id):
    return get_template_items("trainer", owner_id)


def get_user_breeding_farms(owner_id):
    return get_template_items("breeding_farm", owner_id)


def get_user_stallions(owner_id):
    return get_template_items("stallion", owner_id)


def get_user_venues(owner_id):
    return get_template_items("venue", owner_id)


def get_user_race_names(owner_id):
    return get_template_items("race_name", owner_id)


def get_user_criteria(owner_id):
    return get_template_items("criteria", owner_id)


def find_or_create_template_item(template_type, owner_id, value):
    _, name_column = TEMPLATE_CONFIG[template_type]
    value = clean_text(value)

    if not value:
        return None

    items = get_template_items(template_type, owner_id)

    existing = next(
        (
            item
            for item in items
            if clean_text(item[name_column]).casefold() == value.casefold()
        ),
        None,
    )

    if existing:
        return existing["id"]

    success, _ = add_template_item(template_type, owner_id, value)

    if not success:
        items = get_template_items(template_type, owner_id)
        existing = next(
            (
                item
                for item in items
                if clean_text(item[name_column]).casefold() == value.casefold()
            ),
            None,
        )
        return existing["id"] if existing else None

    items = get_template_items(template_type, owner_id)

    created = next(
        (
            item
            for item in items
            if clean_text(item[name_column]).casefold() == value.casefold()
        ),
        None,
    )

    return created["id"] if created else None


def find_template_item_id(template_type, owner_id, value):
    _, name_column = TEMPLATE_CONFIG[template_type]
    value = clean_text(value)

    if not value:
        return None

    items = get_template_items(template_type, owner_id)

    found = next(
        (
            item
            for item in items
            if clean_text(item[name_column]).casefold() == value.casefold()
        ),
        None,
    )

    return found["id"] if found else None


# -------------------------------------------------
# Checklist database functions
# -------------------------------------------------
def add_checklist(
    owner_id,
    horse_id,
    horse_owner_id,
    jockey_id,
    previous_jockey_id,
    trainer_id,
    breeding_farm_id,
    stallion_id,
    broodmare_sire_id,
    venue_id,
    race_name_id,
    distance,
    date_of_race,
    memo,
    finished_place,
    checklist_data,
    program_number=None,
    number_of_horses=None,
    odds=None,
    prize=None,
    bracket_number=None,
    horse_number=None,
    horse_weight=None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if horse_id is not None and date_of_race:
            cursor.execute(
                """
                SELECT id
                FROM checklists
                WHERE owner_id = ? AND horse_id = ? AND date_of_race = ?
                """,
                (owner_id, horse_id, date_of_race),
            )

            if cursor.fetchone():
                return (
                    False,
                    "A checklist for this horse and race date is already registered.",
                )

        checklist_json = (
            json.dumps(checklist_data, ensure_ascii=False)
            if checklist_data
            else None
        )

        cursor.execute(
            """
            INSERT INTO checklists (
                owner_id,
                horse_id,
                horse_owner_id,
                jockey_id,
                previous_jockey_id,
                trainer_id,
                breeding_farm_id,
                stallion_id,
                broodmare_sire_id,
                venue_id,
                race_name_id,
                distance,
                date_of_race,
                memo,
                finished_place,
                checklist,
                program_number,
                number_of_horses,
                odds,
                prize,
                bracket_number,
                horse_number,
                horse_weight
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                horse_id,
                horse_owner_id,
                jockey_id,
                previous_jockey_id,
                trainer_id,
                breeding_farm_id,
                stallion_id,
                broodmare_sire_id,
                venue_id,
                race_name_id,
                distance,
                date_of_race,
                memo,
                finished_place,
                checklist_json,
                program_number,
                number_of_horses,
                odds,
                prize,
                bracket_number,
                horse_number,
                horse_weight,
            ),
        )

        conn.commit()
        return True, "Checklist saved!"

    except sqlite3.IntegrityError:
        return (
            False,
            "A checklist for this horse and race date is already registered.",
        )
    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"
    finally:
        conn.close()


def update_checklist(
    checklist_id,
    owner_id,
    horse_id,
    horse_owner_id,
    jockey_id,
    previous_jockey_id,
    trainer_id,
    breeding_farm_id,
    stallion_id,
    broodmare_sire_id,
    venue_id,
    race_name_id,
    distance,
    date_of_race,
    memo,
    finished_place,
    program_number,
    number_of_horses,
    odds,
    prize,
    checklist_data,
    bracket_number=None,
    horse_number=None,
    horse_weight=None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if horse_id is not None and date_of_race:
            cursor.execute(
                """
                SELECT id
                FROM checklists
                WHERE owner_id = ?
                  AND horse_id = ?
                  AND date_of_race = ?
                  AND id != ?
                """,
                (owner_id, horse_id, date_of_race, checklist_id),
            )

            if cursor.fetchone():
                return (
                    False,
                    "Another checklist for this horse and race date is already registered.",
                )

        checklist_json = (
            json.dumps(checklist_data, ensure_ascii=False)
            if checklist_data
            else None
        )

        cursor.execute(
            """
            UPDATE checklists
            SET
                horse_id = ?,
                horse_owner_id = ?,
                jockey_id = ?,
                previous_jockey_id = ?,
                trainer_id = ?,
                breeding_farm_id = ?,
                stallion_id = ?,
                broodmare_sire_id = ?,
                venue_id = ?,
                race_name_id = ?,
                distance = ?,
                date_of_race = ?,
                memo = ?,
                finished_place = ?,
                checklist = ?,
                program_number = ?,
                number_of_horses = ?,
                odds = ?,
                prize = ?,
                bracket_number = ?,
                horse_number = ?,
                horse_weight = ?
            WHERE id = ? AND owner_id = ?
            """,
            (
                horse_id,
                horse_owner_id,
                jockey_id,
                previous_jockey_id,
                trainer_id,
                breeding_farm_id,
                stallion_id,
                broodmare_sire_id,
                venue_id,
                race_name_id,
                distance,
                date_of_race,
                memo,
                finished_place,
                checklist_json,
                program_number,
                number_of_horses,
                odds,
                prize,
                bracket_number,
                horse_number,
                horse_weight,
                checklist_id,
                owner_id,
            ),
        )

        conn.commit()
        return True, "Checklist updated!"

    except sqlite3.IntegrityError:
        return (
            False,
            "Another checklist for this horse and race date is already registered.",
        )
    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"
    finally:
        conn.close()


def delete_checklist(checklist_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM checklists WHERE id = ? AND owner_id = ?",
            (checklist_id, owner_id),
        )
        conn.commit()
        return True, "Checklist deleted!"
    except sqlite3.Error as error:
        conn.rollback()
        return False, f"Database error: {error}"
    finally:
        conn.close()


def get_checklist_by_id(checklist_id, owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM checklists
            WHERE id = ? AND owner_id = ?
            """,
            (checklist_id, owner_id),
        )
        row = cursor.fetchone()

        return row["id"] if row else None
    finally:
        conn.close()


def find_checklist_id_by_horse_and_date(owner_id, horse_id, date_of_race):
    if horse_id is None or not date_of_race:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM checklists
            WHERE owner_id = ? AND horse_id = ? AND date_of_race = ?
            """,
            (owner_id, horse_id, date_of_race),
        )
        row = cursor.fetchone()

        return row["id"] if row else None
    finally:
        conn.close()


def get_user_checklists(owner_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                checklists.id,
                checklists.horse_id,
                horses.horse_name,
                checklists.horse_owner_id,
                horse_owners.horse_owner_name,
                checklists.jockey_id,
                jockeys.jockey_name,
                checklists.previous_jockey_id,
                prev_jockey.jockey_name AS previous_jockey_name,
                checklists.trainer_id,
                trainers.trainer_name,
                checklists.breeding_farm_id,
                breeding_farms.breeding_farm_name,
                checklists.stallion_id,
                stallions.stallion_name,
                checklists.broodmare_sire_id,
                broodmare_sires.stallion_name AS broodmare_sire_name,
                checklists.venue_id,
                venues.venue_name,
                checklists.race_name_id,
                race_names.race_name,
                checklists.distance,
                checklists.date_of_race,
                checklists.memo,
                checklists.finished_place,
                checklists.checklist,
                checklists.program_number,
                checklists.number_of_horses,
                checklists.odds,
                checklists.prize,
                checklists.bracket_number,
                checklists.horse_number,
                checklists.horse_weight
            FROM checklists
            LEFT JOIN horses ON checklists.horse_id = horses.id
            LEFT JOIN horse_owners
                ON checklists.horse_owner_id = horse_owners.id
            LEFT JOIN jockeys ON checklists.jockey_id = jockeys.id
            LEFT JOIN jockeys AS prev_jockey
                ON checklists.previous_jockey_id = prev_jockey.id
            LEFT JOIN trainers ON checklists.trainer_id = trainers.id
            LEFT JOIN breeding_farms
                ON checklists.breeding_farm_id = breeding_farms.id
            LEFT JOIN stallions ON checklists.stallion_id = stallions.id
            LEFT JOIN stallions AS broodmare_sires
                ON checklists.broodmare_sire_id = broodmare_sires.id
            LEFT JOIN venues ON checklists.venue_id = venues.id
            LEFT JOIN race_names ON checklists.race_name_id = race_names.id
            WHERE checklists.owner_id = ?
            ORDER BY checklists.date_of_race DESC, checklists.id DESC
            """,
            (owner_id,),
        )

        results = cursor.fetchall()

        checklists = []
        for row in results:
            checklists.append(
                {
                    "id": row["id"],
                    "horse_id": row["horse_id"],
                    "horse_name": row["horse_name"] or "No horse selected",
                    "horse_owner_id": row["horse_owner_id"],
                    "horse_owner_name": (
                        row["horse_owner_name"]
                        or "No horse owner selected"
                    ),
                    "jockey_id": row["jockey_id"],
                    "jockey_name": row["jockey_name"] or "No jockey selected",
                    "previous_jockey_id": row["previous_jockey_id"],
                    "previous_jockey_name": (
                        row["previous_jockey_name"]
                        or "No previous jockey selected"
                    ),
                    "trainer_id": row["trainer_id"],
                    "trainer_name": row["trainer_name"] or "No trainer selected",
                    "breeding_farm_id": row["breeding_farm_id"],
                    "breeding_farm_name": (
                        row["breeding_farm_name"]
                        or "No breeding farm selected"
                    ),
                    "stallion_id": row["stallion_id"],
                    "stallion_name": row["stallion_name"] or "No stallion selected",
                    "broodmare_sire_id": row["broodmare_sire_id"],
                    "broodmare_sire_name": (
                        row["broodmare_sire_name"]
                        or "No broodmare sire selected"
                    ),
                    "venue_id": row["venue_id"],
                    "venue_name": row["venue_name"] or "No venue selected",
                    "race_name_id": row["race_name_id"],
                    "race_name": row["race_name"] or "No race name selected",
                    "distance": row["distance"],
                    "date_of_race": row["date_of_race"],
                    "memo": row["memo"] or "",
                    "finished_place": row["finished_place"] or "",
                    "checklist": safe_json_loads(row["checklist"]),
                    "program_number": row["program_number"],
                    "number_of_horses": row["number_of_horses"],
                    "odds": row["odds"],
                    "prize": row["prize"],
                    "bracket_number": row["bracket_number"],
                    "horse_number": row["horse_number"],
                    "horse_weight": row["horse_weight"],
                }
            )

        return checklists

    finally:
        conn.close()


# -------------------------------------------------
# Import functions
# -------------------------------------------------
IMPORT_COLUMN_ALIASES = {
    "id": ["id", "checklist_id"],
    "horse_name": ["horse_name", "horse"],
    "horse_owner_name": ["horse_owner_name", "horse_owner"],
    "jockey_name": ["jockey_name", "jockey"],
    "previous_jockey_name": ["previous_jockey_name", "previous_jockey"],
    "trainer_name": ["trainer_name", "trainer"],
    "breeding_farm_name": ["breeding_farm_name", "breeding_farm"],
    "stallion_name": ["stallion_name", "stallion"],
    "broodmare_sire_name": ["broodmare_sire_name", "broodmare_sire"],
    "venue_name": ["venue_name", "venue"],
    "race_name": ["race_name"],
    "distance": ["distance"],
    "date_of_race": ["date_of_race"],
    "memo": ["memo"],
    "finished_place": ["finished_place"],
    "program_number": ["program_number"],
    "number_of_horses": ["number_of_horses"],
    "odds": ["odds"],
    "prize": ["prize"],
    "bracket_number": ["bracket_number"],
    "horse_number": ["horse_number"],
    "horse_weight": ["horse_weight"],
    "checked_criteria": ["checked_criteria"],
}


def normalize_import_column_name(column_name):
    return (
        clean_text(column_name)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def get_row_value(row, normalized_columns, canonical_name, default=None):
    aliases = IMPORT_COLUMN_ALIASES.get(canonical_name, [canonical_name])

    for alias in aliases:
        if alias in normalized_columns:
            return row[normalized_columns[alias]]

    return default


def build_import_checklist_data(row, normalized_columns, criteria_items):
    criteria_names = {
        criterion["criteria_name"]
        for criterion in criteria_items
    }

    checklist_data = {}

    checked_criteria_value = get_row_value(
        row,
        normalized_columns,
        "checked_criteria",
        "",
    )

    for criterion_name in clean_text(checked_criteria_value).split("|"):
        criterion_name = clean_text(criterion_name)

        if criterion_name and criterion_name in criteria_names:
            checklist_data[criterion_name] = True

    for normalized_name, original_name in normalized_columns.items():
        if not normalized_name.startswith("criteria__"):
            continue

        criterion_name = clean_text(original_name[len("criteria__"):])

        if criterion_name and criterion_name in criteria_names:
            checklist_data[criterion_name] = parse_boolean(row[original_name])

    return checklist_data if any(checklist_data.values()) else None


def import_checklist_dataframe(owner_id, df, criteria_items):
    normalized_columns = {
        normalize_import_column_name(column_name): column_name
        for column_name in df.columns
    }

    if "horse_name" not in normalized_columns and "horse" not in normalized_columns:
        return 0, 0, 0, [
            (
                0,
                "Missing required column: horse_name (or legacy column: horse).",
            )
        ]

    if "date_of_race" not in normalized_columns:
        return 0, 0, 0, [(0, "Missing required column: date_of_race.")]

    added_count = 0
    updated_count = 0
    failed_rows = []

    for index, row in df.iterrows():
        row_number = index + 2

        try:
            checklist_id = parse_optional_int(
                get_row_value(row, normalized_columns, "id")
            )

            horse_name = clean_text(
                get_row_value(row, normalized_columns, "horse_name")
            )
            race_date = normalize_date(
                get_row_value(row, normalized_columns, "date_of_race")
            )

            if not horse_name:
                failed_rows.append((row_number, "Horse name is required."))
                continue

            if not race_date:
                failed_rows.append((row_number, "Date of race is required."))
                continue

            horse_id = find_or_create_template_item(
                "horse",
                owner_id,
                horse_name,
            )

            horse_owner_id = find_or_create_template_item(
                "horse_owner",
                owner_id,
                get_row_value(
                    row,
                    normalized_columns,
                    "horse_owner_name",
                ),
            )

            jockey_id = find_or_create_template_item(
                "jockey",
                owner_id,
                get_row_value(row, normalized_columns, "jockey_name"),
            )

            previous_jockey_id = find_or_create_template_item(
                "jockey",
                owner_id,
                get_row_value(
                    row,
                    normalized_columns,
                    "previous_jockey_name",
                ),
            )

            trainer_id = find_or_create_template_item(
                "trainer",
                owner_id,
                get_row_value(row, normalized_columns, "trainer_name"),
            )

            breeding_farm_id = find_or_create_template_item(
                "breeding_farm",
                owner_id,
                get_row_value(
                    row,
                    normalized_columns,
                    "breeding_farm_name",
                ),
            )

            stallion_id = find_or_create_template_item(
                "stallion",
                owner_id,
                get_row_value(row, normalized_columns, "stallion_name"),
            )

            broodmare_sire_id = find_or_create_template_item(
                "stallion",
                owner_id,
                get_row_value(
                    row,
                    normalized_columns,
                    "broodmare_sire_name",
                ),
            )

            venue_id = find_or_create_template_item(
                "venue",
                owner_id,
                get_row_value(row, normalized_columns, "venue_name"),
            )

            race_name_id = find_or_create_template_item(
                "race_name",
                owner_id,
                get_row_value(row, normalized_columns, "race_name"),
            )

            distance = parse_optional_int(
                get_row_value(row, normalized_columns, "distance")
            )
            memo = clean_text(
                get_row_value(row, normalized_columns, "memo")
            )
            finished_place = clean_text(
                get_row_value(row, normalized_columns, "finished_place")
            )
            program_number = parse_optional_int(
                get_row_value(row, normalized_columns, "program_number")
            )
            number_of_horses = parse_optional_int(
                get_row_value(row, normalized_columns, "number_of_horses")
            )
            odds = parse_optional_float(
                get_row_value(row, normalized_columns, "odds")
            )
            prize = parse_optional_float(
                get_row_value(row, normalized_columns, "prize")
            )
            bracket_number = parse_optional_int(
                get_row_value(row, normalized_columns, "bracket_number")
            )
            horse_number = parse_optional_int(
                get_row_value(row, normalized_columns, "horse_number")
            )
            horse_weight = parse_optional_float(
                get_row_value(row, normalized_columns, "horse_weight")
            )

            checklist_data = build_import_checklist_data(
                row,
                normalized_columns,
                criteria_items,
            )

            target_checklist_id = None

            if checklist_id is not None:
                target_checklist_id = get_checklist_by_id(
                    checklist_id,
                    owner_id,
                )

            if target_checklist_id is None:
                target_checklist_id = find_checklist_id_by_horse_and_date(
                    owner_id,
                    horse_id,
                    race_date,
                )

            if target_checklist_id is not None:
                success, message = update_checklist(
                    checklist_id=target_checklist_id,
                    owner_id=owner_id,
                    horse_id=horse_id,
                    horse_owner_id=horse_owner_id,
                    jockey_id=jockey_id,
                    previous_jockey_id=previous_jockey_id,
                    trainer_id=trainer_id,
                    breeding_farm_id=breeding_farm_id,
                    stallion_id=stallion_id,
                    broodmare_sire_id=broodmare_sire_id,
                    venue_id=venue_id,
                    race_name_id=race_name_id,
                    distance=distance,
                    date_of_race=race_date,
                    memo=memo,
                    finished_place=finished_place,
                    program_number=program_number,
                    number_of_horses=number_of_horses,
                    odds=odds,
                    prize=prize,
                    checklist_data=checklist_data,
                    bracket_number=bracket_number,
                    horse_number=horse_number,
                    horse_weight=horse_weight,
                )

                if success:
                    updated_count += 1
                else:
                    failed_rows.append((row_number, message))

            else:
                success, message = add_checklist(
                    owner_id=owner_id,
                    horse_id=horse_id,
                    horse_owner_id=horse_owner_id,
                    jockey_id=jockey_id,
                    previous_jockey_id=previous_jockey_id,
                    trainer_id=trainer_id,
                    breeding_farm_id=breeding_farm_id,
                    stallion_id=stallion_id,
                    broodmare_sire_id=broodmare_sire_id,
                    venue_id=venue_id,
                    race_name_id=race_name_id,
                    distance=distance,
                    date_of_race=race_date,
                    memo=memo,
                    finished_place=finished_place,
                    checklist_data=checklist_data,
                    program_number=program_number,
                    number_of_horses=number_of_horses,
                    odds=odds,
                    prize=prize,
                    bracket_number=bracket_number,
                    horse_number=horse_number,
                    horse_weight=horse_weight,
                )

                if success:
                    added_count += 1
                else:
                    failed_rows.append((row_number, message))

        except Exception as error:
            failed_rows.append((row_number, str(error)))

    return added_count, updated_count, len(failed_rows), failed_rows


# -------------------------------------------------
# UI helpers
# -------------------------------------------------
def render_template_page(template_type, title, input_label):
    owner_id = st.session_state.user_id
    _, name_column = TEMPLATE_CONFIG[template_type]

    st.header(title)

    with st.form(f"add_{template_type}_form", clear_on_submit=True):
        new_value = st.text_input(input_label)
        submitted = st.form_submit_button("Add")

        if submitted:
            success, message = add_template_item(
                template_type,
                owner_id,
                new_value,
            )
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    st.subheader("Edit or delete registered items")

    items = get_template_items(template_type, owner_id)

    if not items:
        st.info("No items registered yet.")
        return

    for item in items:
        item_id = item["id"]
        item_name = item[name_column]

        with st.expander(item_name):
            edit_value = st.text_input(
                "Name",
                value=item_name,
                key=f"{template_type}_edit_name_{item_id}",
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button(
                    "Update",
                    key=f"{template_type}_update_{item_id}",
                ):
                    success, message = update_template_item(
                        template_type,
                        item_id,
                        owner_id,
                        edit_value,
                    )
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            with col2:
                if st.button(
                    "Delete",
                    key=f"{template_type}_delete_{item_id}",
                ):
                    success, message = delete_template_item(
                        template_type,
                        item_id,
                        owner_id,
                    )
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)


def render_race_checklist_page():
    owner_id = st.session_state.user_id

    st.header("Race Checklist")

    horses = get_user_horses(owner_id)
    horse_owners = get_user_horse_owners(owner_id)
    jockeys = get_user_jockeys(owner_id)
    trainers = get_user_trainers(owner_id)
    breeding_farms = get_user_breeding_farms(owner_id)
    stallions = get_user_stallions(owner_id)
    venues = get_user_venues(owner_id)
    race_names = get_user_race_names(owner_id)
    criteria = get_user_criteria(owner_id)

    horse_options, horse_ids = make_options(horses, "horse_name")
    horse_owner_options, horse_owner_ids = make_options(
        horse_owners,
        "horse_owner_name",
    )
    jockey_options, jockey_ids = make_options(jockeys, "jockey_name")
    trainer_options, trainer_ids = make_options(trainers, "trainer_name")
    breeding_farm_options, breeding_farm_ids = make_options(
        breeding_farms,
        "breeding_farm_name",
    )
    stallion_options, stallion_ids = make_options(stallions, "stallion_name")
    venue_options, venue_ids = make_options(venues, "venue_name")
    race_options, race_ids = make_options(race_names, "race_name")

    with st.form("race_checklist_form", clear_on_submit=True):
        selected_horse_idx = st.selectbox(
            "Select Horse (optional)",
            range(len(horse_options)),
            format_func=lambda i: horse_options[i],
        )
        selected_horse_owner_idx = st.selectbox(
            "Select Horse Owner (optional)",
            range(len(horse_owner_options)),
            format_func=lambda i: horse_owner_options[i],
        )
        selected_jockey_idx = st.selectbox(
            "Select Jockey (optional)",
            range(len(jockey_options)),
            format_func=lambda i: jockey_options[i],
        )
        selected_previous_jockey_idx = st.selectbox(
            "Select Previous Jockey (optional)",
            range(len(jockey_options)),
            format_func=lambda i: jockey_options[i],
        )
        selected_trainer_idx = st.selectbox(
            "Select Trainer (optional)",
            range(len(trainer_options)),
            format_func=lambda i: trainer_options[i],
        )
        selected_breeding_farm_idx = st.selectbox(
            "Select Breeding Farm (optional)",
            range(len(breeding_farm_options)),
            format_func=lambda i: breeding_farm_options[i],
        )
        selected_stallion_idx = st.selectbox(
            "Select Stallion (optional)",
            range(len(stallion_options)),
            format_func=lambda i: stallion_options[i],
        )
        selected_broodmare_sire_idx = st.selectbox(
            "Select Broodmare Sire (optional)",
            range(len(stallion_options)),
            format_func=lambda i: stallion_options[i],
        )
        selected_venue_idx = st.selectbox(
            "Select Venue (optional)",
            range(len(venue_options)),
            format_func=lambda i: venue_options[i],
        )
        selected_race_idx = st.selectbox(
            "Select Race Name (optional)",
            range(len(race_options)),
            format_func=lambda i: race_options[i],
        )

        distance = st.number_input(
            "Distance (meters)",
            min_value=0,
            max_value=5000,
            value=0,
            step=100,
        )
        date_of_race = st.date_input(
            "Date of Race",
            min_value=date(1980, 1, 1),
            value=date.today(),
        )
        memo = st.text_area("Memo (optional)")
        finished_place = st.text_input("Finished Place (optional)")

        col1, col2 = st.columns(2)

        with col1:
            program_number = st.number_input(
                "Program Number (optional) (レース番号)",
                min_value=0,
                max_value=12,
                value=0,
            )
            number_of_horses = st.number_input(
                "Number of Horses (optional) (出走頭数)",
                min_value=0,
                max_value=18,
                value=0,
            )
            odds = st.number_input(
                "Odds (optional)",
                min_value=0.0,
                max_value=999.9,
                value=0.0,
                step=0.1,
            )
            prize = st.number_input(
                "Prize (optional) (¥)",
                min_value=0.0,
                max_value=1000000000.0,
                value=0.0,
                step=1000.0,
            )

        with col2:
            bracket_number = st.number_input(
                "Bracket Number (optional) (枠番)",
                min_value=0,
                max_value=8,
                value=0,
            )
            horse_number = st.number_input(
                "Horse Number (optional) (馬番)",
                min_value=0,
                max_value=18,
                value=0,
            )
            horse_weight = st.number_input(
                "Horse Weight (optional) (馬体重 kg)",
                min_value=0.0,
                max_value=999.9,
                value=0.0,
                step=0.1,
            )

        st.write("Check the criteria that apply for this race (optional):")

        checklist_data = {}
        for criterion in criteria:
            criterion_name = criterion["criteria_name"]
            checklist_data[criterion_name] = st.checkbox(criterion_name)

        save_clicked = st.form_submit_button("Save Checklist")

    if save_clicked:
        success, message = add_checklist(
            owner_id=owner_id,
            horse_id=get_selected_id(horse_ids, selected_horse_idx),
            horse_owner_id=get_selected_id(
                horse_owner_ids,
                selected_horse_owner_idx,
            ),
            jockey_id=get_selected_id(jockey_ids, selected_jockey_idx),
            previous_jockey_id=get_selected_id(
                jockey_ids,
                selected_previous_jockey_idx,
            ),
            trainer_id=get_selected_id(trainer_ids, selected_trainer_idx),
            breeding_farm_id=get_selected_id(
                breeding_farm_ids,
                selected_breeding_farm_idx,
            ),
            stallion_id=get_selected_id(stallion_ids, selected_stallion_idx),
            broodmare_sire_id=get_selected_id(
                stallion_ids,
                selected_broodmare_sire_idx,
            ),
            venue_id=get_selected_id(venue_ids, selected_venue_idx),
            race_name_id=get_selected_id(race_ids, selected_race_idx),
            distance=to_optional_int(distance),
            date_of_race=date_of_race.isoformat(),
            memo=clean_text(memo),
            finished_place=clean_text(finished_place),
            checklist_data=checklist_data if any(checklist_data.values()) else None,
            program_number=to_optional_int(program_number),
            number_of_horses=to_optional_int(number_of_horses),
            odds=to_optional_float(odds),
            prize=to_optional_float(prize),
            bracket_number=to_optional_int(bracket_number),
            horse_number=to_optional_int(horse_number),
            horse_weight=to_optional_float(horse_weight),
        )

        if success:
            st.success(message)
        else:
            st.error(message)

    render_batch_import_section(owner_id, criteria)


def render_batch_import_section(owner_id, criteria_items):
    st.markdown("---")
    st.subheader("Batch Import Race Checklists (CSV or Excel)")

    st.caption(
        "Download the template or filtered-results CSV, edit it, and upload "
        "it here. Every current checklist criterion is included as a "
        "`criteria__...` column. Use 1 / TRUE / YES for checked criteria."
    )

    st.download_button(
        label="📥 Download CSV Template",
        data=build_import_template_bytes(criteria_items),
        file_name="race_checklist_import_template.csv",
        mime="text/csv",
    )

    uploaded_file = st.file_uploader(
        (
            "Upload CSV or XLSX. Required columns: horse_name and "
            "date_of_race. Optional id updates the matching checklist. "
            "Without id, horse_name + date_of_race updates a matching record "
            "or creates a new checklist."
        ),
        type=["csv", "xlsx"],
        key="batch_checklist_file",
    )

    if uploaded_file is None:
        return

    if not st.button("Import uploaded file", key="import_uploaded_file_button"):
        return

    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=object)
        else:
            df = pd.read_excel(uploaded_file, dtype=object)

        added_count, updated_count, failed_count, failed_rows = (
            import_checklist_dataframe(
                owner_id,
                df,
                criteria_items,
            )
        )

        st.success(
            f"Import completed. Added: {added_count}. "
            f"Updated: {updated_count}. Failed: {failed_count}."
        )

        if failed_rows:
            failed_text = "; ".join(
                f"Row {row_number}: {message}"
                for row_number, message in failed_rows[:30]
            )

            if len(failed_rows) > 30:
                failed_text += f"; and {len(failed_rows) - 30} more."

            st.warning("Some rows were not imported. " + failed_text)

    except Exception as error:
        st.error(f"Error reading file: {error}")


# -------------------------------------------------
# Filter functions
# -------------------------------------------------
def filter_checklists(
    checklists,
    selected_filters,
    selected_venue_ids,
    criteria_filters,
    criteria_mode,
    distance_from,
    distance_to,
    date_from,
    date_to,
    memo_keyword,
    program_number,
    number_of_horses,
    finished_places,
    exclude_finished_places,
    odds_from,
    odds_to,
    prize_from,
    prize_to,
    enable_bracket_filter,
    bracket_from,
    bracket_to,
    enable_horse_filter,
    horse_from,
    horse_to,
    enable_weight_filter,
    weight_from,
    weight_to,
):
    filtered = []

    for entry in checklists:
        matches = True

        for field_name, selected_id in selected_filters.items():
            if selected_id is not None and entry.get(field_name) != selected_id:
                matches = False
                break

        if not matches:
            continue

        if selected_venue_ids and entry.get("venue_id") not in selected_venue_ids:
            continue

        entry_date = parse_race_date(entry.get("date_of_race"))

        if date_from and (entry_date is None or entry_date < date_from):
            continue

        if date_to and (entry_date is None or entry_date > date_to):
            continue

        checklist_map = entry.get("checklist") or {}

        if criteria_filters:
            if criteria_mode == "AND":
                if not all(
                    checklist_map.get(item, False)
                    for item in criteria_filters
                ):
                    continue

            elif criteria_mode == "OR":
                if not any(
                    checklist_map.get(item, False)
                    for item in criteria_filters
                ):
                    continue

            elif criteria_mode == "NOT matched by criteria":
                if any(
                    checklist_map.get(item, False)
                    for item in criteria_filters
                ):
                    continue

        distance_value = entry.get("distance")
        distance_value = distance_value if distance_value is not None else 0

        if distance_value < distance_from or distance_value > distance_to:
            continue

        if memo_keyword.strip():
            keyword = memo_keyword.strip().lower()

            searchable_text = " | ".join(
                [
                    clean_text(entry.get("memo")).lower(),
                    clean_text(entry.get("horse_name")).lower(),
                    clean_text(entry.get("horse_owner_name")).lower(),
                    clean_text(entry.get("jockey_name")).lower(),
                    clean_text(entry.get("previous_jockey_name")).lower(),
                    clean_text(entry.get("trainer_name")).lower(),
                    clean_text(entry.get("breeding_farm_name")).lower(),
                    clean_text(entry.get("stallion_name")).lower(),
                    clean_text(entry.get("broodmare_sire_name")).lower(),
                    clean_text(entry.get("venue_name")).lower(),
                    clean_text(entry.get("race_name")).lower(),
                ]
            )

            if keyword not in searchable_text:
                continue

        if program_number > 0:
            if entry.get("program_number") != program_number:
                continue

        if number_of_horses > 0:
            if entry.get("number_of_horses") != number_of_horses:
                continue

        entry_finished_place = clean_text(entry.get("finished_place"))

        if finished_places and entry_finished_place not in finished_places:
            continue

        if exclude_finished_places and entry_finished_place in exclude_finished_places:
            continue

        odds_value = entry.get("odds")
        if odds_value is None:
            if odds_from > 0:
                continue
        elif odds_value < odds_from or odds_value > odds_to:
            continue

        prize_value = entry.get("prize")
        if prize_value is None:
            if prize_from > 0:
                continue
        elif prize_value < prize_from or prize_value > prize_to:
            continue

        if enable_bracket_filter:
            bracket_value = entry.get("bracket_number")

            if bracket_value is None:
                continue

            if bracket_value < bracket_from or bracket_value > bracket_to:
                continue

        if enable_horse_filter:
            horse_number_value = entry.get("horse_number")

            if horse_number_value is None:
                continue

            if horse_number_value < horse_from or horse_number_value > horse_to:
                continue

        if enable_weight_filter:
            horse_weight_value = entry.get("horse_weight")

            if horse_weight_value is None:
                continue

            if horse_weight_value < weight_from or horse_weight_value > weight_to:
                continue

        filtered.append(entry)

    return filtered


def build_summary_dataframe(checklists):
    summary_rows = []

    for entry in checklists:
        checked_criteria = [
            key
            for key, value in (entry.get("checklist") or {}).items()
            if value
        ]

        summary_rows.append(
            {
                "ID": entry["id"],
                "Date": entry.get("date_of_race") or "",
                "Horse": entry.get("horse_name") or "",
                "Horse Owner": entry.get("horse_owner_name") or "",
                "Jockey": entry.get("jockey_name") or "",
                "Race": entry.get("race_name") or "",
                "Venue": entry.get("venue_name") or "",
                "Distance": entry.get("distance") or "",
                "Place": entry.get("finished_place") or "",
                "Odds": entry.get("odds")
                if entry.get("odds") is not None
                else "",
                "Prize (¥)": (
                    f"¥{entry.get('prize'):,.0f}"
                    if entry.get("prize") is not None
                    else ""
                ),
                "Criteria": " | ".join(checked_criteria),
            }
        )

    return pd.DataFrame(summary_rows)


def calculate_review_metrics(filtered_checklists):
    completed = [
        entry
        for entry in filtered_checklists
        if clean_text(entry.get("finished_place")).isdigit()
    ]

    first = [
        entry
        for entry in completed
        if int(clean_text(entry.get("finished_place"))) == 1
    ]

    within_3 = [
        entry
        for entry in completed
        if int(clean_text(entry.get("finished_place"))) in (1, 2, 3)
    ]

    within_5 = [
        entry
        for entry in completed
        if int(clean_text(entry.get("finished_place")))
        in (1, 2, 3, 4, 5)
    ]

    odds_values = [
        entry["odds"]
        for entry in within_3
        if isinstance(entry.get("odds"), (int, float))
    ]

    prize_values = [
        entry["prize"]
        for entry in within_5
        if isinstance(entry.get("prize"), (int, float))
    ]

    return {
        "total": len(filtered_checklists),
        "completed": len(completed),
        "win_rate": (
            len(first) / len(completed) * 100
            if completed
            else None
        ),
        "top_3_rate": (
            len(within_3) / len(completed) * 100
            if completed
            else None
        ),
        "average_top_3_odds": (
            sum(odds_values) / len(odds_values)
            if odds_values
            else None
        ),
        "average_top_5_prize": (
            sum(prize_values) / len(prize_values)
            if prize_values
            else None
        ),
    }


# -------------------------------------------------
# Checklist editor
# -------------------------------------------------
def render_checklist_editor(
    entry,
    owner_id,
    horses,
    horse_owners,
    jockeys,
    trainers,
    breeding_farms,
    stallions,
    venues,
    race_names,
    criteria,
):
    st.subheader(f"Edit Checklist #{entry['id']}")

    horse_options, horse_ids = make_options(horses, "horse_name")
    horse_owner_options, horse_owner_ids = make_options(
        horse_owners,
        "horse_owner_name",
    )
    jockey_options, jockey_ids = make_options(jockeys, "jockey_name")
    trainer_options, trainer_ids = make_options(trainers, "trainer_name")
    breeding_farm_options, breeding_farm_ids = make_options(
        breeding_farms,
        "breeding_farm_name",
    )
    stallion_options, stallion_ids = make_options(stallions, "stallion_name")
    venue_options, venue_ids = make_options(venues, "venue_name")
    race_options, race_ids = make_options(race_names, "race_name")

    def selected_index(ids, entry_id):
        return ids.index(entry_id) if entry_id in ids else 0

    existing_date = parse_race_date(entry.get("date_of_race")) or date.today()

    with st.form(f"edit_checklist_form_{entry['id']}"):
        edit_horse_idx = st.selectbox(
            "Horse",
            range(len(horse_options)),
            index=selected_index(horse_ids, entry.get("horse_id")),
            format_func=lambda i: horse_options[i],
        )

        edit_horse_owner_idx = st.selectbox(
            "Horse Owner",
            range(len(horse_owner_options)),
            index=selected_index(
                horse_owner_ids,
                entry.get("horse_owner_id"),
            ),
            format_func=lambda i: horse_owner_options[i],
        )

        edit_jockey_idx = st.selectbox(
            "Jockey",
            range(len(jockey_options)),
            index=selected_index(jockey_ids, entry.get("jockey_id")),
            format_func=lambda i: jockey_options[i],
        )

        edit_previous_jockey_idx = st.selectbox(
            "Previous Jockey",
            range(len(jockey_options)),
            index=selected_index(
                jockey_ids,
                entry.get("previous_jockey_id"),
            ),
            format_func=lambda i: jockey_options[i],
        )

        edit_trainer_idx = st.selectbox(
            "Trainer",
            range(len(trainer_options)),
            index=selected_index(trainer_ids, entry.get("trainer_id")),
            format_func=lambda i: trainer_options[i],
        )

        edit_breeding_farm_idx = st.selectbox(
            "Breeding Farm",
            range(len(breeding_farm_options)),
            index=selected_index(
                breeding_farm_ids,
                entry.get("breeding_farm_id"),
            ),
            format_func=lambda i: breeding_farm_options[i],
        )

        edit_stallion_idx = st.selectbox(
            "Stallion",
            range(len(stallion_options)),
            index=selected_index(stallion_ids, entry.get("stallion_id")),
            format_func=lambda i: stallion_options[i],
        )

        edit_broodmare_sire_idx = st.selectbox(
            "Broodmare Sire",
            range(len(stallion_options)),
            index=selected_index(
                stallion_ids,
                entry.get("broodmare_sire_id"),
            ),
            format_func=lambda i: stallion_options[i],
        )

        edit_venue_idx = st.selectbox(
            "Venue",
            range(len(venue_options)),
            index=selected_index(venue_ids, entry.get("venue_id")),
            format_func=lambda i: venue_options[i],
        )

        edit_race_idx = st.selectbox(
            "Race Name",
            range(len(race_options)),
            index=selected_index(race_ids, entry.get("race_name_id")),
            format_func=lambda i: race_options[i],
        )

        edit_distance = st.number_input(
            "Distance (meters)",
            min_value=0,
            max_value=5000,
            value=int(entry.get("distance") or 0),
            step=100,
        )

        edit_date = st.date_input(
            "Date of Race",
            value=existing_date,
        )

        edit_memo = st.text_area(
            "Memo",
            value=entry.get("memo") or "",
        )

        edit_finished_place = st.text_input(
            "Finished Place",
            value=entry.get("finished_place") or "",
        )

        col1, col2 = st.columns(2)

        with col1:
            edit_program_number = st.number_input(
                "Program Number (レース番号)",
                min_value=0,
                max_value=12,
                value=int(entry.get("program_number") or 0),
            )

            edit_number_of_horses = st.number_input(
                "Number of Horses (出走頭数)",
                min_value=0,
                max_value=18,
                value=int(entry.get("number_of_horses") or 0),
            )

            edit_odds = st.number_input(
                "Odds",
                min_value=0.0,
                max_value=999.9,
                value=float(entry.get("odds") or 0.0),
                step=0.1,
            )

            edit_prize = st.number_input(
                "Prize (¥)",
                min_value=0.0,
                max_value=1000000000.0,
                value=float(entry.get("prize") or 0.0),
                step=1000.0,
            )

        with col2:
            edit_bracket_number = st.number_input(
                "Bracket Number (枠番)",
                min_value=0,
                max_value=8,
                value=int(entry.get("bracket_number") or 0),
            )

            edit_horse_number = st.number_input(
                "Horse Number (馬番)",
                min_value=0,
                max_value=18,
                value=int(entry.get("horse_number") or 0),
            )

            edit_horse_weight = st.number_input(
                "Horse Weight (kg)",
                min_value=0.0,
                max_value=999.9,
                value=float(entry.get("horse_weight") or 0.0),
                step=0.1,
            )

        st.write("Checklist criteria:")

        edit_checklist_data = {}
        existing_checklist_data = entry.get("checklist") or {}

        for criterion in criteria:
            criterion_name = criterion["criteria_name"]
            edit_checklist_data[criterion_name] = st.checkbox(
                criterion_name,
                value=bool(
                    existing_checklist_data.get(criterion_name, False)
                ),
            )

        update_clicked = st.form_submit_button("Update Checklist")

    delete_clicked = st.button(
        "Delete This Checklist",
        key=f"delete_checklist_{entry['id']}",
        type="secondary",
    )

    if update_clicked:
        success, message = update_checklist(
            checklist_id=entry["id"],
            owner_id=owner_id,
            horse_id=get_selected_id(horse_ids, edit_horse_idx),
            horse_owner_id=get_selected_id(
                horse_owner_ids,
                edit_horse_owner_idx,
            ),
            jockey_id=get_selected_id(jockey_ids, edit_jockey_idx),
            previous_jockey_id=get_selected_id(
                jockey_ids,
                edit_previous_jockey_idx,
            ),
            trainer_id=get_selected_id(trainer_ids, edit_trainer_idx),
            breeding_farm_id=get_selected_id(
                breeding_farm_ids,
                edit_breeding_farm_idx,
            ),
            stallion_id=get_selected_id(
                stallion_ids,
                edit_stallion_idx,
            ),
            broodmare_sire_id=get_selected_id(
                stallion_ids,
                edit_broodmare_sire_idx,
            ),
            venue_id=get_selected_id(venue_ids, edit_venue_idx),
            race_name_id=get_selected_id(race_ids, edit_race_idx),
            distance=to_optional_int(edit_distance),
            date_of_race=edit_date.isoformat(),
            memo=clean_text(edit_memo),
            finished_place=clean_text(edit_finished_place),
            program_number=to_optional_int(edit_program_number),
            number_of_horses=to_optional_int(edit_number_of_horses),
            odds=to_optional_float(edit_odds),
            prize=to_optional_float(edit_prize),
            checklist_data=(
                edit_checklist_data
                if any(edit_checklist_data.values())
                else None
            ),
            bracket_number=to_optional_int(edit_bracket_number),
            horse_number=to_optional_int(edit_horse_number),
            horse_weight=to_optional_float(edit_horse_weight),
        )

        if success:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

    if delete_clicked:
        success, message = delete_checklist(entry["id"], owner_id)

        if success:
            st.success(message)
            st.session_state.pop("selected_review_checklist_id", None)
            st.rerun()
        else:
            st.error(message)


# -------------------------------------------------
# Second Filter UI
# -------------------------------------------------
def render_second_filter_section(
    owner_id,
    first_filtered_checklists,
    horse_ids,
    horse_options,
    horse_owner_ids,
    horse_owner_options,
    jockey_ids,
    jockey_options,
    trainer_ids,
    trainer_options,
    breeding_farm_ids,
    breeding_farm_options,
    stallion_ids,
    stallion_options,
    venue_ids,
    venue_options,
    race_ids,
    race_options,
    criteria,
):
    st.subheader("Second Filter")

    st.caption(
        "The second filter calculates dominance within the first-filter "
        "results. It does not change the first-filter results list."
    )

    enable_second_filter = st.checkbox(
        "Enable Second Filter",
        key=second_filter_key(owner_id, "enabled"),
    )

    if not enable_second_filter:
        return None, False

    clear_second_col1, clear_second_col2 = st.columns([3, 1])

    with clear_second_col1:
        st.caption(
            "All conditions below are used only to calculate second-filter "
            "dominance within the first-filter results."
        )

    with clear_second_col2:
        if st.button(
            "Clear Second Filter",
            key=second_filter_key(owner_id, "reset_button"),
            type="secondary",
            use_container_width=True,
        ):
            reset_second_filter_values(owner_id)
            st.session_state[second_filter_load_version_key(owner_id)] += 1
            st.rerun()

    left_col, right_col = st.columns(2)

    with left_col:
        selected_horse_id = render_second_filter_selectbox(
            "Second Filter by Horse",
            owner_id,
            "horse_id",
            horse_ids,
            horse_options,
        )

        selected_horse_owner_id = render_second_filter_selectbox(
            "Second Filter by Horse Owner",
            owner_id,
            "horse_owner_id",
            horse_owner_ids,
            horse_owner_options,
        )

        selected_jockey_id = render_second_filter_selectbox(
            "Second Filter by Jockey",
            owner_id,
            "jockey_id",
            jockey_ids,
            jockey_options,
        )

        selected_previous_jockey_id = render_second_filter_selectbox(
            "Second Filter by Previous Jockey",
            owner_id,
            "previous_jockey_id",
            jockey_ids,
            jockey_options,
        )

        selected_trainer_id = render_second_filter_selectbox(
            "Second Filter by Trainer",
            owner_id,
            "trainer_id",
            trainer_ids,
            trainer_options,
        )

        selected_breeding_farm_id = render_second_filter_selectbox(
            "Second Filter by Breeding Farm",
            owner_id,
            "breeding_farm_id",
            breeding_farm_ids,
            breeding_farm_options,
        )

        selected_stallion_id = render_second_filter_selectbox(
            "Second Filter by Stallion",
            owner_id,
            "stallion_id",
            stallion_ids,
            stallion_options,
        )

        selected_broodmare_sire_id = render_second_filter_selectbox(
            "Second Filter by Broodmare Sire",
            owner_id,
            "broodmare_sire_id",
            stallion_ids,
            stallion_options,
        )

        second_selected_venue_ids = st.multiselect(
            "Second Filter by Venues",
            venue_ids[1:],
            format_func=lambda venue_id: venue_options[
                venue_ids.index(venue_id)
            ],
            key=second_filter_key(owner_id, "venue_ids"),
        )

        selected_race_name_id = render_second_filter_selectbox(
            "Second Filter by Race Name",
            owner_id,
            "race_name_id",
            race_ids,
            race_options,
        )

        second_filter_memo_keyword = st.text_input(
            "Second Filter memo or text contains keyword",
            key=second_filter_key(owner_id, "memo_keyword"),
        )

        second_filter_program_number = st.number_input(
            "Second Filter by Program Number",
            min_value=0,
            max_value=12,
            step=1,
            help="0 = all",
            key=second_filter_key(owner_id, "program_number"),
        )

        second_filter_number_of_horses = st.number_input(
            "Second Filter by Number of Horses",
            min_value=0,
            max_value=18,
            step=1,
            help="0 = all",
            key=second_filter_key(owner_id, "number_of_horses"),
        )

        second_filter_odds_from = st.number_input(
            "Second Filter From Odds",
            min_value=0.0,
            max_value=999.9,
            step=0.1,
            key=second_filter_key(owner_id, "odds_from"),
        )

        second_filter_odds_to = st.number_input(
            "Second Filter To Odds",
            min_value=0.0,
            max_value=999.9,
            step=0.1,
            key=second_filter_key(owner_id, "odds_to"),
        )

        second_filter_prize_from = st.number_input(
            "Second Filter From Prize (¥)",
            min_value=0.0,
            max_value=1000000000.0,
            step=1000.0,
            key=second_filter_key(owner_id, "prize_from"),
        )

        second_filter_prize_to = st.number_input(
            "Second Filter To Prize (¥)",
            min_value=0.0,
            max_value=1000000000.0,
            step=1000.0,
            key=second_filter_key(owner_id, "prize_to"),
        )

    with right_col:
        second_filter_criteria = st.multiselect(
            "Second Filter by Criteria",
            [criterion["criteria_name"] for criterion in criteria],
            key=second_filter_key(owner_id, "criteria"),
        )

        second_criteria_mode = st.radio(
            "Second Filter criteria match mode",
            ["AND", "OR", "NOT matched by criteria"],
            horizontal=True,
            key=second_filter_key(owner_id, "criteria_mode"),
        )

        second_filter_distance_from = st.number_input(
            "Second Filter From Distance (meters)",
            min_value=0,
            max_value=5000,
            step=100,
            key=second_filter_key(owner_id, "distance_from"),
        )

        second_filter_distance_to = st.number_input(
            "Second Filter To Distance (meters)",
            min_value=0,
            max_value=5000,
            step=100,
            key=second_filter_key(owner_id, "distance_to"),
        )

        second_filter_date_from = st.date_input(
            "Second Filter From Date",
            key=second_filter_key(owner_id, "date_from"),
        )

        second_filter_date_to = st.date_input(
            "Second Filter To Date",
            key=second_filter_key(owner_id, "date_to"),
        )

        second_filter_places = st.multiselect(
            "Second Filter by Finished Place (着順)",
            [str(i) for i in range(1, 19)],
            help="Example: Select 1, 2, 3 for top-three results.",
            key=second_filter_key(owner_id, "places"),
        )

        second_exclude_finished_places = st.multiselect(
            "Second Filter Exclude Finished Place (着順)",
            [str(i) for i in range(1, 19)],
            help="Example: Select 1, 2, 3 to exclude first-, second-, and third-place results.",
            key=second_filter_key(owner_id, "exclude_places"),
        )

        second_enable_bracket_filter = st.checkbox(
            "Enable Second Filter Bracket Number",
            key=second_filter_key(owner_id, "enable_bracket_filter"),
        )

        second_filter_bracket_from = st.number_input(
            "Second Filter From Bracket Number (枠番)",
            min_value=1,
            max_value=8,
            step=1,
            key=second_filter_key(owner_id, "bracket_from"),
        )

        second_filter_bracket_to = st.number_input(
            "Second Filter To Bracket Number (枠番)",
            min_value=1,
            max_value=8,
            step=1,
            key=second_filter_key(owner_id, "bracket_to"),
        )

        second_enable_horse_filter = st.checkbox(
            "Enable Second Filter Horse Number",
            key=second_filter_key(owner_id, "enable_horse_filter"),
        )

        second_filter_horse_from = st.number_input(
            "Second Filter From Horse Number (馬番)",
            min_value=1,
            max_value=18,
            step=1,
            key=second_filter_key(owner_id, "horse_from"),
        )

        second_filter_horse_to = st.number_input(
            "Second Filter To Horse Number (馬番)",
            min_value=1,
            max_value=18,
            step=1,
            key=second_filter_key(owner_id, "horse_to"),
        )

        second_enable_weight_filter = st.checkbox(
            "Enable Second Filter Horse Weight",
            key=second_filter_key(owner_id, "enable_weight_filter"),
        )

        second_filter_weight_from = st.number_input(
            "Second Filter From Horse Weight (kg)",
            min_value=0.0,
            max_value=999.9,
            step=0.1,
            key=second_filter_key(owner_id, "weight_from"),
        )

        second_filter_weight_to = st.number_input(
            "Second Filter To Horse Weight (kg)",
            min_value=0.0,
            max_value=999.9,
            step=0.1,
            key=second_filter_key(owner_id, "weight_to"),
        )

    second_selected_filters = {
        "horse_id": selected_horse_id,
        "horse_owner_id": selected_horse_owner_id,
        "jockey_id": selected_jockey_id,
        "previous_jockey_id": selected_previous_jockey_id,
        "trainer_id": selected_trainer_id,
        "breeding_farm_id": selected_breeding_farm_id,
        "stallion_id": selected_stallion_id,
        "broodmare_sire_id": selected_broodmare_sire_id,
        "race_name_id": selected_race_name_id,
    }

    second_filtered_checklists = filter_checklists(
        checklists=first_filtered_checklists,
        selected_filters=second_selected_filters,
        selected_venue_ids=second_selected_venue_ids,
        criteria_filters=second_filter_criteria,
        criteria_mode=second_criteria_mode,
        distance_from=second_filter_distance_from,
        distance_to=second_filter_distance_to,
        date_from=second_filter_date_from,
        date_to=second_filter_date_to,
        memo_keyword=second_filter_memo_keyword,
        program_number=second_filter_program_number,
        number_of_horses=second_filter_number_of_horses,
        finished_places=second_filter_places,
        exclude_finished_places=second_exclude_finished_places,
        odds_from=second_filter_odds_from,
        odds_to=second_filter_odds_to,
        prize_from=second_filter_prize_from,
        prize_to=second_filter_prize_to,
        enable_bracket_filter=second_enable_bracket_filter,
        bracket_from=second_filter_bracket_from,
        bracket_to=second_filter_bracket_to,
        enable_horse_filter=second_enable_horse_filter,
        horse_from=second_filter_horse_from,
        horse_to=second_filter_horse_to,
        enable_weight_filter=second_enable_weight_filter,
        weight_from=second_filter_weight_from,
        weight_to=second_filter_weight_to,
    )

    return second_filtered_checklists, True


# -------------------------------------------------
# Checklist Review
# -------------------------------------------------
def render_checklist_review_page():
    owner_id = st.session_state.user_id

    initialize_filter_defaults(owner_id)
    initialize_second_filter_defaults(owner_id)

    st.header("Checklist Review")

    checklists = get_user_checklists(owner_id)
    horses = get_user_horses(owner_id)
    horse_owners = get_user_horse_owners(owner_id)
    jockeys = get_user_jockeys(owner_id)
    trainers = get_user_trainers(owner_id)
    breeding_farms = get_user_breeding_farms(owner_id)
    stallions = get_user_stallions(owner_id)
    venues = get_user_venues(owner_id)
    race_names = get_user_race_names(owner_id)
    criteria = get_user_criteria(owner_id)

    horse_options, horse_ids = make_options(horses, "horse_name")
    horse_owner_options, horse_owner_ids = make_options(
        horse_owners,
        "horse_owner_name",
    )
    jockey_options, jockey_ids = make_options(jockeys, "jockey_name")
    trainer_options, trainer_ids = make_options(trainers, "trainer_name")
    breeding_farm_options, breeding_farm_ids = make_options(
        breeding_farms,
        "breeding_farm_name",
    )
    stallion_options, stallion_ids = make_options(stallions, "stallion_name")
    venue_options, venue_ids = make_options(venues, "venue_name")
    race_options, race_ids = make_options(race_names, "race_name")

    if st.session_state.pop(
        saved_filter_key(owner_id, "clear_title_on_next_run"),
        False,
    ):
        st.session_state[saved_filter_key(owner_id, "new_title")] = ""

    saved_filter_message = st.session_state.pop(
        saved_filter_key(owner_id, "save_message"),
        None,
    )

    filter_import_message = st.session_state.pop(
        saved_filter_key(owner_id, "import_message"),
        None,
    )

    st.subheader("Saved Filters")

    if saved_filter_message:
        st.success(saved_filter_message)

    if filter_import_message:
        st.success(filter_import_message)

    saved_filters = get_saved_filters(owner_id)

    with st.expander("💾 Backup or Restore Saved Filters", expanded=False):
        st.caption(
            "Download a JSON backup before deployment. After a deployment "
            "or local storage reset, upload the same JSON file to restore "
            "your saved filters."
        )

        backup_col1, backup_col2 = st.columns(2)

        with backup_col1:
            st.download_button(
                label="📥 Export Saved Filters Backup",
                data=build_saved_filters_backup_bytes(owner_id),
                file_name=(
                    "horse_checklist_saved_filters_"
                    + datetime.now().strftime("%Y%m%d_%H%M%S")
                    + ".json"
                ),
                mime="application/json",
                use_container_width=True,
            )

        with backup_col2:
            st.caption(
                f"{len(saved_filters)} saved filter(s) will be included "
                "in the backup."
            )

        st.markdown("---")
        st.write("Restore Saved Filters")

        uploaded_filter_backup = st.file_uploader(
            "Upload saved filters backup JSON",
            type=["json"],
            key=saved_filter_key(owner_id, "backup_import_file"),
        )

        if st.button(
            "Import Saved Filters Backup",
            key=saved_filter_key(owner_id, "backup_import_button"),
            use_container_width=True,
        ):
            if uploaded_filter_backup is None:
                st.error("Please select a JSON backup file first.")
            else:
                success, message, imported_count, skipped_count = (
                    import_saved_filters_backup(
                        owner_id,
                        uploaded_filter_backup,
                    )
                )

                if success:
                    st.session_state[
                        saved_filter_key(owner_id, "import_message")
                    ] = (
                        f"{message} Imported: {imported_count}. "
                        f"Skipped duplicates or invalid entries: "
                        f"{skipped_count}."
                    )
                    st.rerun()
                else:
                    st.error(message)

    with st.expander("💾 Load or Delete Saved Filters", expanded=False):
        if saved_filters:
            saved_filter_lookup = {
                saved_filter["id"]: saved_filter
                for saved_filter in saved_filters
            }
            saved_filter_ids = list(saved_filter_lookup.keys())

            saved_filter_col1, saved_filter_col2 = st.columns([3, 1])

            with saved_filter_col1:
                selected_saved_filter_id = st.selectbox(
                    "Select a saved filter",
                    saved_filter_ids,
                    format_func=lambda filter_id: (
                        saved_filter_lookup[filter_id]["title"]
                        + " — saved "
                        + saved_filter_lookup[filter_id]["created_at"]
                    ),
                    key=saved_filter_key(owner_id, "selected_id"),
                )

            with saved_filter_col2:
                st.write("")
                st.write("")

                if st.button(
                    "Load Saved Filter",
                    key=saved_filter_key(owner_id, "load_button"),
                    use_container_width=True,
                ):
                    selected_saved_filter = saved_filter_lookup[
                        selected_saved_filter_id
                    ]

                    apply_saved_filter_to_session(
                        owner_id,
                        selected_saved_filter["filter_data"],
                        selected_saved_filter["title"],
                    )

                    st.session_state.pop(
                        "selected_review_checklist_id",
                        None,
                    )
                    st.rerun()

            delete_filter_col1, delete_filter_col2 = st.columns([3, 1])

            with delete_filter_col1:
                st.caption(
                    "Load a filter, then change any conditions in Search and Filter Checklists."
                )

            with delete_filter_col2:
                if st.button(
                    "Delete Saved Filter",
                    key=saved_filter_key(owner_id, "delete_button"),
                    type="secondary",
                    use_container_width=True,
                ):
                    success, message = delete_saved_filter(
                        selected_saved_filter_id,
                        owner_id,
                    )

                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

        else:
            st.info("No saved filters yet.")

    with st.expander("🔍 Search and Filter Checklists", expanded=True):
        reset_col1, reset_col2 = st.columns([3, 1])

        with reset_col1:
            active_filter_title = clean_text(
                st.session_state.get(
                    saved_filter_key(owner_id, "active_filter_title"),
                    "",
                )
            )

            if active_filter_title:
                st.caption(
                    f"Loaded saved filter: {active_filter_title}. "
                    "The fields below contain its conditions and can be changed."
                )
            else:
                st.caption(
                    "Set filter conditions below. Changes are applied immediately."
                )

        with reset_col2:
            if st.button(
                "Clear All Filters",
                key=saved_filter_key(owner_id, "reset_button"),
                type="secondary",
                use_container_width=True,
            ):
                reset_filter_values(owner_id)
                reset_second_filter_values(owner_id)
                st.session_state[filter_load_version_key(owner_id)] += 1
                st.session_state[second_filter_load_version_key(owner_id)] += 1
                st.session_state[second_filter_key(owner_id, "enabled")] = False
                st.session_state.pop("selected_review_checklist_id", None)
                st.rerun()

        left_col, right_col = st.columns(2)

        with left_col:
            selected_horse_id = render_filter_selectbox(
                "Filter by Horse",
                owner_id,
                "horse_id",
                horse_ids,
                horse_options,
            )

            selected_horse_owner_id = render_filter_selectbox(
                "Filter by Horse Owner",
                owner_id,
                "horse_owner_id",
                horse_owner_ids,
                horse_owner_options,
            )

            selected_jockey_id = render_filter_selectbox(
                "Filter by Jockey",
                owner_id,
                "jockey_id",
                jockey_ids,
                jockey_options,
            )

            selected_previous_jockey_id = render_filter_selectbox(
                "Filter by Previous Jockey",
                owner_id,
                "previous_jockey_id",
                jockey_ids,
                jockey_options,
            )

            selected_trainer_id = render_filter_selectbox(
                "Filter by Trainer",
                owner_id,
                "trainer_id",
                trainer_ids,
                trainer_options,
            )

            selected_breeding_farm_id = render_filter_selectbox(
                "Filter by Breeding Farm",
                owner_id,
                "breeding_farm_id",
                breeding_farm_ids,
                breeding_farm_options,
            )

            selected_stallion_id = render_filter_selectbox(
                "Filter by Stallion",
                owner_id,
                "stallion_id",
                stallion_ids,
                stallion_options,
            )

            selected_broodmare_sire_id = render_filter_selectbox(
                "Filter by Broodmare Sire",
                owner_id,
                "broodmare_sire_id",
                stallion_ids,
                stallion_options,
            )

            selected_venue_ids = st.multiselect(
                "Filter by Venues",
                venue_ids[1:],
                format_func=lambda venue_id: venue_options[
                    venue_ids.index(venue_id)
                ],
                help="Select multiple venues, for example 東京 and 中山.",
                key=saved_filter_key(owner_id, "venue_ids"),
            )

            selected_race_name_id = render_filter_selectbox(
                "Filter by Race Name",
                owner_id,
                "race_name_id",
                race_ids,
                race_options,
            )

            filter_memo_keyword = st.text_input(
                "Memo or text contains keyword",
                key=saved_filter_key(owner_id, "memo_keyword"),
            )

            filter_program_number = st.number_input(
                "Filter by Program Number",
                min_value=0,
                max_value=12,
                step=1,
                help="0 = all",
                key=saved_filter_key(owner_id, "program_number"),
            )

            filter_number_of_horses = st.number_input(
                "Filter by Number of Horses",
                min_value=0,
                max_value=18,
                step=1,
                help="0 = all",
                key=saved_filter_key(owner_id, "number_of_horses"),
            )

            filter_odds_from = st.number_input(
                "From Odds",
                min_value=0.0,
                max_value=999.9,
                step=0.1,
                key=saved_filter_key(owner_id, "odds_from"),
            )

            filter_odds_to = st.number_input(
                "To Odds",
                min_value=0.0,
                max_value=999.9,
                step=0.1,
                key=saved_filter_key(owner_id, "odds_to"),
            )

            filter_prize_from = st.number_input(
                "From Prize (¥)",
                min_value=0.0,
                max_value=1000000000.0,
                step=1000.0,
                key=saved_filter_key(owner_id, "prize_from"),
            )

            filter_prize_to = st.number_input(
                "To Prize (¥)",
                min_value=0.0,
                max_value=1000000000.0,
                step=1000.0,
                key=saved_filter_key(owner_id, "prize_to"),
            )

        with right_col:
            filter_criteria = st.multiselect(
                "Filter by Criteria",
                [criterion["criteria_name"] for criterion in criteria],
                key=saved_filter_key(owner_id, "criteria"),
            )

            criteria_mode = st.radio(
                "Criteria match mode",
                ["AND", "OR", "NOT matched by criteria"],
                horizontal=True,
                key=saved_filter_key(owner_id, "criteria_mode"),
            )

            filter_distance_from = st.number_input(
                "From Distance (meters)",
                min_value=0,
                max_value=5000,
                step=100,
                key=saved_filter_key(owner_id, "distance_from"),
            )

            filter_distance_to = st.number_input(
                "To Distance (meters)",
                min_value=0,
                max_value=5000,
                step=100,
                key=saved_filter_key(owner_id, "distance_to"),
            )

            filter_date_from = st.date_input(
                "From Date",
                key=saved_filter_key(owner_id, "date_from"),
            )

            filter_date_to = st.date_input(
                "To Date",
                key=saved_filter_key(owner_id, "date_to"),
            )

            filter_places = st.multiselect(
                "Filter by Finished Place (着順)",
                [str(i) for i in range(1, 19)],
                help="Example: Select 1, 2, 3 for top-three results.",
                key=saved_filter_key(owner_id, "places"),
            )

            exclude_finished_places = st.multiselect(
                "Exclude Finished Place (着順)",
                [str(i) for i in range(1, 19)],
                help="Example: Select 1, 2, 3 to show all results except first-, second-, and third-place horses.",
                key=saved_filter_key(owner_id, "exclude_places"),
            )

            enable_bracket_filter = st.checkbox(
                "Enable Bracket Number filter",
                key=saved_filter_key(owner_id, "enable_bracket_filter"),
            )

            filter_bracket_from = st.number_input(
                "From Bracket Number (枠番)",
                min_value=1,
                max_value=8,
                step=1,
                key=saved_filter_key(owner_id, "bracket_from"),
            )

            filter_bracket_to = st.number_input(
                "To Bracket Number (枠番)",
                min_value=1,
                max_value=8,
                step=1,
                key=saved_filter_key(owner_id, "bracket_to"),
            )

            enable_horse_filter = st.checkbox(
                "Enable Horse Number filter",
                key=saved_filter_key(owner_id, "enable_horse_filter"),
            )

            filter_horse_from = st.number_input(
                "From Horse Number (馬番)",
                min_value=1,
                max_value=18,
                step=1,
                key=saved_filter_key(owner_id, "horse_from"),
            )

            filter_horse_to = st.number_input(
                "To Horse Number (馬番)",
                min_value=1,
                max_value=18,
                step=1,
                key=saved_filter_key(owner_id, "horse_to"),
            )

            enable_weight_filter = st.checkbox(
                "Enable Horse Weight filter",
                key=saved_filter_key(owner_id, "enable_weight_filter"),
            )

            filter_weight_from = st.number_input(
                "From Horse Weight (kg)",
                min_value=0.0,
                max_value=999.9,
                step=0.1,
                key=saved_filter_key(owner_id, "weight_from"),
            )

            filter_weight_to = st.number_input(
                "To Horse Weight (kg)",
                min_value=0.0,
                max_value=999.9,
                step=0.1,
                key=saved_filter_key(owner_id, "weight_to"),
            )

        filter_save_col1, filter_save_col2 = st.columns([3, 1])

        with filter_save_col1:
            saved_filter_title = st.text_input(
                "Save current filter with title",
                placeholder="Example: Tokyo and Nakayama excluding top 3",
                key=saved_filter_key(owner_id, "new_title"),
            )

        with filter_save_col2:
            st.write("")
            st.write("")

            if st.button(
                "Save Current Filter",
                key=saved_filter_key(owner_id, "save_button"),
                use_container_width=True,
            ):
                success, message = save_filter(
                    owner_id,
                    saved_filter_title,
                    collect_current_filter_data(owner_id),
                )

                if success:
                    st.session_state[saved_filter_key(owner_id, "save_message")] = (
                        message
                    )
                    st.session_state[
                        saved_filter_key(owner_id, "clear_title_on_next_run")
                    ] = True
                    st.rerun()
                else:
                    st.error(message)

    selected_filters = {
        "horse_id": selected_horse_id,
        "horse_owner_id": selected_horse_owner_id,
        "jockey_id": selected_jockey_id,
        "previous_jockey_id": selected_previous_jockey_id,
        "trainer_id": selected_trainer_id,
        "breeding_farm_id": selected_breeding_farm_id,
        "stallion_id": selected_stallion_id,
        "broodmare_sire_id": selected_broodmare_sire_id,
        "race_name_id": selected_race_name_id,
    }

    first_filtered_checklists = filter_checklists(
        checklists=checklists,
        selected_filters=selected_filters,
        selected_venue_ids=selected_venue_ids,
        criteria_filters=filter_criteria,
        criteria_mode=criteria_mode,
        distance_from=filter_distance_from,
        distance_to=filter_distance_to,
        date_from=filter_date_from,
        date_to=filter_date_to,
        memo_keyword=filter_memo_keyword,
        program_number=filter_program_number,
        number_of_horses=filter_number_of_horses,
        finished_places=filter_places,
        exclude_finished_places=exclude_finished_places,
        odds_from=filter_odds_from,
        odds_to=filter_odds_to,
        prize_from=filter_prize_from,
        prize_to=filter_prize_to,
        enable_bracket_filter=enable_bracket_filter,
        bracket_from=filter_bracket_from,
        bracket_to=filter_bracket_to,
        enable_horse_filter=enable_horse_filter,
        horse_from=filter_horse_from,
        horse_to=filter_horse_to,
        enable_weight_filter=enable_weight_filter,
        weight_from=filter_weight_from,
        weight_to=filter_weight_to,
    )

    st.caption(
        f"First filter results: {len(first_filtered_checklists)} checklist(s)"
    )

    with st.expander(
        "🔎 Second Filter (Dominance Only — First Results Stay Visible)",
        expanded=False,
    ):
        second_filtered_checklists, second_filter_enabled = (
            render_second_filter_section(
                owner_id=owner_id,
                first_filtered_checklists=first_filtered_checklists,
                horse_ids=horse_ids,
                horse_options=horse_options,
                horse_owner_ids=horse_owner_ids,
                horse_owner_options=horse_owner_options,
                jockey_ids=jockey_ids,
                jockey_options=jockey_options,
                trainer_ids=trainer_ids,
                trainer_options=trainer_options,
                breeding_farm_ids=breeding_farm_ids,
                breeding_farm_options=breeding_farm_options,
                stallion_ids=stallion_ids,
                stallion_options=stallion_options,
                venue_ids=venue_ids,
                venue_options=venue_options,
                race_ids=race_ids,
                race_options=race_options,
                criteria=criteria,
            )
        )

    if second_filter_enabled:
        first_filter_total = len(first_filtered_checklists)
        second_filter_total = len(second_filtered_checklists)

        dominance_percentage = (
            second_filter_total / first_filter_total * 100
            if first_filter_total > 0
            else 0.0
        )

        st.subheader("Second Filter Dominance")

        dominance_col1, dominance_col2, dominance_col3 = st.columns(3)

        dominance_col1.metric(
            "First Filter Results",
            first_filter_total,
        )

        dominance_col2.metric(
            "Second Filter Results",
            second_filter_total,
        )

        dominance_col3.metric(
            "Dominance in First Filter",
            f"{dominance_percentage:.1f}%",
        )

        st.caption(
            f"The second filter matches {second_filter_total} out of "
            f"{first_filter_total} first-filter result(s): "
            f"{dominance_percentage:.1f}%. "
            "The results list below still shows all first-filter results."
        )

    review_metrics = calculate_review_metrics(first_filtered_checklists)

    st.subheader("Review Summary")

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    metric_col1.metric("Total Results", review_metrics["total"])
    metric_col2.metric("Completed", review_metrics["completed"])
    metric_col3.metric(
        "Top 3 Rate",
        (
            f"{review_metrics['top_3_rate']:.1f}%"
            if review_metrics["top_3_rate"] is not None
            else "N/A"
        ),
    )
    metric_col4.metric(
        "Win Rate",
        (
            f"{review_metrics['win_rate']:.1f}%"
            if review_metrics["win_rate"] is not None
            else "N/A"
        ),
    )

    metric_col5, metric_col6 = st.columns(2)

    metric_col5.metric(
        "Average Odds (Top 3)",
        (
            f"{review_metrics['average_top_3_odds']:.1f}"
            if review_metrics["average_top_3_odds"] is not None
            else "N/A"
        ),
    )
    metric_col6.metric(
        "Average Prize (Top 5)",
        format_yen(review_metrics["average_top_5_prize"]),
    )

    st.subheader("Filtered Checklists")

    if first_filtered_checklists:
        st.download_button(
            label="📥 Download Filtered Results CSV",
            data=build_csv_download_bytes(
                first_filtered_checklists,
                criteria,
            ),
            file_name=(
                "horse_checklist_filtered_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".csv"
            ),
            mime="text/csv",
        )

        total_results = len(first_filtered_checklists)

        display_col1, display_col2 = st.columns([2, 2])

        with display_col1:
            page_size_options = [25, 50, 100, 200, "Show all"]

            saved_page_size = st.session_state.get(
                saved_filter_key(owner_id, "page_size"),
                50,
            )

            if saved_page_size not in page_size_options:
                saved_page_size = 50

            selected_page_size = st.selectbox(
                "Results per page",
                page_size_options,
                index=page_size_options.index(saved_page_size),
                key=saved_filter_key(owner_id, "page_size_selector"),
            )

        if selected_page_size == "Show all":
            page_size = total_results
        else:
            page_size = int(selected_page_size)

        total_pages = max(1, (total_results + page_size - 1) // page_size)

        with display_col2:
            current_page = st.number_input(
                "Page",
                min_value=1,
                max_value=total_pages,
                value=min(
                    int(
                        st.session_state.get(
                            saved_filter_key(owner_id, "page_number"),
                            1,
                        )
                    ),
                    total_pages,
                ),
                step=1,
                key=saved_filter_key(owner_id, "page_number_input"),
            )

        st.session_state[saved_filter_key(owner_id, "page_size")] = (
            selected_page_size
        )
        st.session_state[saved_filter_key(owner_id, "page_number")] = current_page

        paginated_checklists = get_paginated_items(
            first_filtered_checklists,
            current_page,
            page_size,
        )

        first_item_number = (current_page - 1) * page_size + 1
        last_item_number = min(current_page * page_size, total_results)

        st.caption(
            f"Showing {first_item_number}-{last_item_number} of "
            f"{total_results} filtered checklist(s). "
            "Summary metrics above are calculated from all filtered results."
        )

        summary_df = build_summary_dataframe(paginated_checklists)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        checklist_lookup = {
            entry["id"]: entry
            for entry in paginated_checklists
        }

        if checklist_lookup:
            selected_review_checklist_id = st.selectbox(
                "Select checklist on this page to edit",
                list(checklist_lookup.keys()),
                format_func=lambda checklist_id: (
                    f"#{checklist_id} | "
                    f"{checklist_lookup[checklist_id].get('date_of_race') or ''} | "
                    f"{checklist_lookup[checklist_id].get('horse_name') or ''} | "
                    f"{checklist_lookup[checklist_id].get('horse_owner_name') or ''} | "
                    f"{checklist_lookup[checklist_id].get('venue_name') or ''}"
                ),
                key="selected_review_checklist_id",
            )

            selected_entry = checklist_lookup.get(selected_review_checklist_id)

            if selected_entry:
                with st.expander(
                    f"Edit Checklist #{selected_entry['id']}",
                    expanded=False,
                ):
                    render_checklist_editor(
                        entry=selected_entry,
                        owner_id=owner_id,
                        horses=horses,
                        horse_owners=horse_owners,
                        jockeys=jockeys,
                        trainers=trainers,
                        breeding_farms=breeding_farms,
                        stallions=stallions,
                        venues=venues,
                        race_names=race_names,
                        criteria=criteria,
                    )

    else:
        st.info("No checklists match the current filters.")


# -------------------------------------------------
# Account settings
# -------------------------------------------------
def render_account_settings_page():
    owner_id = st.session_state.user_id

    st.header("Account Settings")
    st.subheader("Change Password")

    st.caption(
        "Enter your current password and a new password. Your password is "
        "stored securely as a bcrypt hash."
    )

    with st.form("change_password_form", clear_on_submit=True):
        current_password = st.text_input(
            "Current Password",
            type="password",
        )

        new_password = st.text_input(
            "New Password",
            type="password",
        )

        confirm_new_password = st.text_input(
            "Confirm New Password",
            type="password",
        )

        change_password_clicked = st.form_submit_button("Change Password")

    if change_password_clicked:
        if not current_password or not new_password or not confirm_new_password:
            st.error("Please complete all password fields.")
        elif new_password != confirm_new_password:
            st.error("New password and confirmation do not match.")
        else:
            success, message = change_user_password(
                owner_id,
                current_password,
                new_password,
            )

            if success:
                st.success(message)
            else:
                st.error(message)


# -------------------------------------------------
# App routing
# -------------------------------------------------
def render_login_page():
    st.title("Horse Checklist App")

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_clicked = st.form_submit_button("Login")

        if login_clicked:
            success, display_name, user_id = login_user(username, password)

            if success:
                st.session_state.logged_in = True
                st.session_state.display_name = display_name
                st.session_state.user_id = user_id
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with register_tab:
        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Username", key="register_username")
            display_name = st.text_input("Display Name")
            password = st.text_input(
                "Password",
                type="password",
                key="register_password",
            )
            password_confirm = st.text_input(
                "Confirm Password",
                type="password",
            )
            invitation_code = st.text_input("Invitation Code")
            register_clicked = st.form_submit_button("Register")

        if register_clicked:
            username = clean_text(username)
            display_name = clean_text(display_name)
            invitation_code = clean_text(invitation_code)

            if not username or not display_name or not password or not invitation_code:
                st.error("Please complete all fields.")
            elif password != password_confirm:
                st.error("Passwords do not match.")
            else:
                success, message = register_user(
                    username,
                    display_name,
                    password,
                    invitation_code,
                )

                if success:
                    st.success(message)
                else:
                    st.error(message)


def main():
    init_db()

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        render_login_page()
        return

    st.sidebar.title("Horse Checklist App")
    st.sidebar.write(f"Logged in as: {st.session_state.display_name}")

    page = st.sidebar.radio(
        "Menu",
        [
            "Race Checklist",
            "Checklist Review",
            "Account Settings",
            "Horses",
            "Horse Owners",
            "Jockeys",
            "Trainers",
            "Breeding Farms",
            "Stallions",
            "Venues",
            "Race Names",
            "Criteria",
        ],
    )

    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()

    if page == "Race Checklist":
        render_race_checklist_page()
    elif page == "Checklist Review":
        render_checklist_review_page()
    elif page == "Account Settings":
        render_account_settings_page()
    elif page == "Horses":
        render_template_page("horse", "Horses", "Horse Name")
    elif page == "Horse Owners":
        render_template_page(
            "horse_owner",
            "Horse Owners",
            "Horse Owner Name",
        )
    elif page == "Jockeys":
        render_template_page("jockey", "Jockeys", "Jockey Name")
    elif page == "Trainers":
        render_template_page("trainer", "Trainers", "Trainer Name")
    elif page == "Breeding Farms":
        render_template_page(
            "breeding_farm",
            "Breeding Farms",
            "Breeding Farm Name",
        )
    elif page == "Stallions":
        render_template_page("stallion", "Stallions", "Stallion Name")
    elif page == "Venues":
        render_template_page("venue", "Venues", "Venue Name")
    elif page == "Race Names":
        render_template_page("race_name", "Race Names", "Race Name")
    elif page == "Criteria":
        render_template_page("criteria", "Criteria", "Criteria Name")


if __name__ == "__main__":
    main()
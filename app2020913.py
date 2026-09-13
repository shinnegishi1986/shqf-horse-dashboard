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

    # Create referenced tables first.
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

    # Safe migrations for databases created by older app versions.
    cursor.execute("PRAGMA table_info(checklists)")
    existing_columns = {row["name"] for row in cursor.fetchall()}

    required_columns = {
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

    conn.commit()
    conn.close()


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def clean_text(value):
    if value is None:
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
        value = int(value)
        return value if value > 0 else None
    except (ValueError, TypeError):
        return None


def to_optional_float(value):
    try:
        value = float(value)
        return value if value > 0 else None
    except (ValueError, TypeError):
        return None


def make_options(items, label_key):
    labels = ["(No selection)"] + [item[label_key] for item in items]
    ids = [None] + [item["id"] for item in items]
    return labels, ids


def get_selected_id(options_ids, selected_index):
    if selected_index < 0 or selected_index >= len(options_ids):
        return None
    return options_ids[selected_index]


def checklist_to_export_rows(checklists):
    rows = []

    for entry in checklists:
        checked_criteria = [
            criterion
            for criterion, checked in (entry.get("checklist") or {}).items()
            if checked
        ]

        rows.append(
            {
                "id": entry.get("id"),
                "horse_name": entry.get("horse_name", ""),
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
        )

    return rows


def build_csv_download_bytes(filtered_checklists, encoding="utf-8-sig"):
    export_rows = checklist_to_export_rows(filtered_checklists)
    df = pd.DataFrame(export_rows)

    if df.empty:
        df = pd.DataFrame(
            columns=[
                "id",
                "horse_name",
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
        )

    return df.to_csv(index=False).encode(encoding, errors="replace")


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
# Template table helpers
# -------------------------------------------------
TEMPLATE_CONFIG = {
    "horse": ("horses", "horse_name"),
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


# Compatibility functions, so the rest of the app remains easy to understand.
def get_user_horses(owner_id):
    return get_template_items("horse", owner_id)


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


# -------------------------------------------------
# Checklist database functions
# -------------------------------------------------
def add_checklist(
    owner_id,
    horse_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                horse_id,
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
            if clean_text(item[name_column]).lower() == value.lower()
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
                if clean_text(item[name_column]).lower() == value.lower()
            ),
            None,
        )
        return existing["id"] if existing else None

    items = get_template_items(template_type, owner_id)

    created = next(
        (
            item
            for item in items
            if clean_text(item[name_column]).lower() == value.lower()
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
            if clean_text(item[name_column]).lower() == value.lower()
        ),
        None,
    )

    return found["id"] if found else None


def render_race_checklist_page():
    owner_id = st.session_state.user_id

    st.header("Race Checklist")

    horses = get_user_horses(owner_id)
    jockeys = get_user_jockeys(owner_id)
    trainers = get_user_trainers(owner_id)
    breeding_farms = get_user_breeding_farms(owner_id)
    stallions = get_user_stallions(owner_id)
    venues = get_user_venues(owner_id)
    race_names = get_user_race_names(owner_id)
    criteria = get_user_criteria(owner_id)

    horse_options, horse_ids = make_options(horses, "horse_name")
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
        selected_horse_idx = st.selectbox("Select Horse (optional)", range(len(horse_options)), format_func=lambda i: horse_options[i])
        selected_jockey_idx = st.selectbox("Select Jockey (optional)", range(len(jockey_options)), format_func=lambda i: jockey_options[i])
        selected_previous_jockey_idx = st.selectbox("Select Previous Jockey (optional)", range(len(jockey_options)), format_func=lambda i: jockey_options[i])
        selected_trainer_idx = st.selectbox("Select Trainer (optional)", range(len(trainer_options)), format_func=lambda i: trainer_options[i])
        selected_breeding_farm_idx = st.selectbox("Select Breeding Farm (optional)", range(len(breeding_farm_options)), format_func=lambda i: breeding_farm_options[i])
        selected_stallion_idx = st.selectbox("Select Stallion (optional)", range(len(stallion_options)), format_func=lambda i: stallion_options[i])
        selected_broodmare_sire_idx = st.selectbox("Select Broodmare Sire (optional)", range(len(stallion_options)), format_func=lambda i: stallion_options[i])
        selected_venue_idx = st.selectbox("Select Venue (optional)", range(len(venue_options)), format_func=lambda i: venue_options[i])
        selected_race_idx = st.selectbox("Select Race Name (optional)", range(len(race_options)), format_func=lambda i: race_options[i])

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
                "Prize (optional)",
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

    render_batch_import_section(owner_id)


def render_batch_import_section(owner_id):
    st.markdown("---")
    st.subheader("Batch Import Race Checklists (CSV or Excel)")

    sample_data = pd.DataFrame(
        {
            "horse": ["Sample Horse A", "Sample Horse B"],
            "jockey": ["", ""],
            "previous_jockey": ["", ""],
            "trainer": ["", ""],
            "breeding_farm": ["", ""],
            "stallion": ["", ""],
            "broodmare_sire": ["", ""],
            "venue": ["", ""],
            "race_name": ["Demo Race", "G1 Spring Stakes"],
            "distance": [1600, 1800],
            "date_of_race": ["2025-04-01", "2025/06/07"],
            "memo": ["First sample entry", "Second entry"],
        }
    )

    template_bytes = io.BytesIO()
    sample_data.to_csv(template_bytes, index=False)
    template_bytes.seek(0)

    st.download_button(
        label="📥 Download CSV Template",
        data=template_bytes,
        file_name="race_checklist_template.csv",
        mime="text/csv",
    )

    uploaded_file = st.file_uploader(
        (
            "Upload CSV or XLSX with columns: horse, jockey, previous_jockey, "
            "trainer, breeding_farm, stallion, broodmare_sire, venue, "
            "race_name, distance, date_of_race, memo"
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
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        df.columns = [
            str(column).strip().lower().replace(" ", "_")
            for column in df.columns
        ]

        required_columns = [
            "horse",
            "jockey",
            "previous_jockey",
            "trainer",
            "breeding_farm",
            "stallion",
            "broodmare_sire",
            "venue",
            "race_name",
            "distance",
            "date_of_race",
            "memo",
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            st.error(
                "Missing required columns: " + ", ".join(missing_columns)
            )
            return

        success_count = 0
        failed_rows = []

        for index, row in df.iterrows():
            try:
                horse_id = find_or_create_template_item(
                    "horse",
                    owner_id,
                    row["horse"],
                )
                jockey_id = find_template_item_id(
                    "jockey",
                    owner_id,
                    row["jockey"],
                )
                previous_jockey_id = find_template_item_id(
                    "jockey",
                    owner_id,
                    row["previous_jockey"],
                )
                trainer_id = find_template_item_id(
                    "trainer",
                    owner_id,
                    row["trainer"],
                )
                breeding_farm_id = find_template_item_id(
                    "breeding_farm",
                    owner_id,
                    row["breeding_farm"],
                )
                stallion_id = find_or_create_template_item(
                    "stallion",
                    owner_id,
                    row["stallion"],
                )
                broodmare_sire_id = find_or_create_template_item(
                    "stallion",
                    owner_id,
                    row["broodmare_sire"],
                )
                venue_id = find_template_item_id(
                    "venue",
                    owner_id,
                    row["venue"],
                )
                race_name_id = find_or_create_template_item(
                    "race_name",
                    owner_id,
                    row["race_name"],
                )

                distance_value = None
                if pd.notna(row["distance"]):
                    try:
                        distance_value = int(float(row["distance"]))
                    except (ValueError, TypeError):
                        distance_value = None

                race_date = normalize_date(row["date_of_race"])
                memo_value = (
                    clean_text(row["memo"])
                    if pd.notna(row["memo"])
                    else ""
                )

                success, message = add_checklist(
                    owner_id=owner_id,
                    horse_id=horse_id,
                    jockey_id=jockey_id,
                    previous_jockey_id=previous_jockey_id,
                    trainer_id=trainer_id,
                    breeding_farm_id=breeding_farm_id,
                    stallion_id=stallion_id,
                    broodmare_sire_id=broodmare_sire_id,
                    venue_id=venue_id,
                    race_name_id=race_name_id,
                    distance=distance_value,
                    date_of_race=race_date,
                    memo=memo_value,
                    finished_place=None,
                    checklist_data=None,
                )

                if success:
                    success_count += 1
                else:
                    failed_rows.append((index + 2, message))

            except Exception as error:
                failed_rows.append((index + 2, str(error)))

        st.success(f"Imported {success_count} checklist(s).")

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


def filter_checklists(
    checklists,
    selected_filters,
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

        entry_date = parse_race_date(entry.get("date_of_race"))

        if date_from and (entry_date is None or entry_date < date_from):
            continue

        if date_to and (entry_date is None or entry_date > date_to):
            continue

        checklist_map = entry.get("checklist") or {}

        if criteria_filters:
            if criteria_mode == "AND":
                if not all(checklist_map.get(item, False) for item in criteria_filters):
                    continue

            elif criteria_mode == "OR":
                if not any(checklist_map.get(item, False) for item in criteria_filters):
                    continue

            elif criteria_mode == "NOT matched by criteria":
                if any(checklist_map.get(item, False) for item in criteria_filters):
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

        if finished_places:
            if clean_text(entry.get("finished_place")) not in finished_places:
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
                "Jockey": entry.get("jockey_name") or "",
                "Race": entry.get("race_name") or "",
                "Venue": entry.get("venue_name") or "",
                "Distance": entry.get("distance") or "",
                "Place": entry.get("finished_place") or "",
                "Odds": entry.get("odds") if entry.get("odds") is not None else "",
                "Prize": entry.get("prize") if entry.get("prize") is not None else "",
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
        if int(clean_text(entry.get("finished_place"))) in (1, 2, 3, 4, 5)
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
        "win_rate": (len(first) / len(completed) * 100) if completed else None,
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


def render_checklist_editor(entry, owner_id, horses, jockeys, trainers, breeding_farms, stallions, venues, race_names, criteria):
    st.subheader(f"Edit Checklist #{entry['id']}")

    horse_options, horse_ids = make_options(horses, "horse_name")
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
                "Prize",
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
                value=bool(existing_checklist_data.get(criterion_name, False)),
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


def render_checklist_review_page():
    owner_id = st.session_state.user_id

    st.header("Checklist Review")

    checklists = get_user_checklists(owner_id)
    horses = get_user_horses(owner_id)
    jockeys = get_user_jockeys(owner_id)
    trainers = get_user_trainers(owner_id)
    breeding_farms = get_user_breeding_farms(owner_id)
    stallions = get_user_stallions(owner_id)
    venues = get_user_venues(owner_id)
    race_names = get_user_race_names(owner_id)
    criteria = get_user_criteria(owner_id)

    horse_options, horse_ids = make_options(horses, "horse_name")
    jockey_options, jockey_ids = make_options(jockeys, "jockey_name")
    trainer_options, trainer_ids = make_options(trainers, "trainer_name")
    breeding_farm_options, breeding_farm_ids = make_options(
        breeding_farms,
        "breeding_farm_name",
    )
    stallion_options, stallion_ids = make_options(stallions, "stallion_name")
    venue_options, venue_ids = make_options(venues, "venue_name")
    race_options, race_ids = make_options(race_names, "race_name")

    with st.expander("🔍 Search and Filter Checklists", expanded=True):
        left_col, right_col = st.columns(2)

        with left_col:
            filter_horse_idx = st.selectbox(
                "Filter by Horse",
                range(len(horse_options)),
                format_func=lambda i: horse_options[i],
                key="filter_horse",
            )

            filter_jockey_idx = st.selectbox(
                "Filter by Jockey",
                range(len(jockey_options)),
                format_func=lambda i: jockey_options[i],
                key="filter_jockey",
            )

            filter_previous_jockey_idx = st.selectbox(
                "Filter by Previous Jockey",
                range(len(jockey_options)),
                format_func=lambda i: jockey_options[i],
                key="filter_previous_jockey",
            )

            filter_trainer_idx = st.selectbox(
                "Filter by Trainer",
                range(len(trainer_options)),
                format_func=lambda i: trainer_options[i],
                key="filter_trainer",
            )

            filter_breeding_farm_idx = st.selectbox(
                "Filter by Breeding Farm",
                range(len(breeding_farm_options)),
                format_func=lambda i: breeding_farm_options[i],
                key="filter_breeding_farm",
            )

            filter_stallion_idx = st.selectbox(
                "Filter by Stallion",
                range(len(stallion_options)),
                format_func=lambda i: stallion_options[i],
                key="filter_stallion",
            )

            filter_broodmare_sire_idx = st.selectbox(
                "Filter by Broodmare Sire",
                range(len(stallion_options)),
                format_func=lambda i: stallion_options[i],
                key="filter_broodmare_sire",
            )

            filter_venue_idx = st.selectbox(
                "Filter by Venue",
                range(len(venue_options)),
                format_func=lambda i: venue_options[i],
                key="filter_venue",
            )

            filter_race_idx = st.selectbox(
                "Filter by Race Name",
                range(len(race_options)),
                format_func=lambda i: race_options[i],
                key="filter_race",
            )

            filter_memo_keyword = st.text_input(
                "Memo or text contains keyword",
                key="filter_memo_keyword",
            )

            filter_program_number = st.number_input(
                "Filter by Program Number",
                min_value=0,
                max_value=12,
                value=0,
                help="0 = all",
                key="filter_program_number",
            )

            filter_number_of_horses = st.number_input(
                "Filter by Number of Horses",
                min_value=0,
                max_value=18,
                value=0,
                help="0 = all",
                key="filter_number_of_horses",
            )

            filter_odds_from = st.number_input(
                "From Odds",
                min_value=0.0,
                max_value=999.9,
                value=0.0,
                step=0.1,
                key="filter_odds_from",
            )

            filter_odds_to = st.number_input(
                "To Odds",
                min_value=0.0,
                max_value=999.9,
                value=999.9,
                step=0.1,
                key="filter_odds_to",
            )

            filter_prize_from = st.number_input(
                "From Prize",
                min_value=0.0,
                max_value=1000000000.0,
                value=0.0,
                step=1000.0,
                key="filter_prize_from",
            )

            filter_prize_to = st.number_input(
                "To Prize",
                min_value=0.0,
                max_value=1000000000.0,
                value=1000000000.0,
                step=1000.0,
                key="filter_prize_to",
            )

        with right_col:
            filter_criteria = st.multiselect(
                "Filter by Criteria",
                [criterion["criteria_name"] for criterion in criteria],
                key="filter_criteria",
            )

            criteria_mode = st.radio(
                "Criteria match mode",
                ["AND", "OR", "NOT matched by criteria"],
                horizontal=True,
                key="criteria_mode",
            )

            filter_distance_from = st.number_input(
                "From Distance (meters)",
                min_value=0,
                max_value=5000,
                value=0,
                step=100,
                key="filter_distance_from",
            )

            filter_distance_to = st.number_input(
                "To Distance (meters)",
                min_value=0,
                max_value=5000,
                value=5000,
                step=100,
                key="filter_distance_to",
            )

            filter_date_from = st.date_input(
                "From Date",
                value=None,
                key="filter_date_from",
            )

            filter_date_to = st.date_input(
                "To Date",
                value=None,
                key="filter_date_to",
            )

            filter_places = st.multiselect(
                "Filter by Finished Place (着順)",
                [str(i) for i in range(1, 19)],
                help="Example: Select 1, 2, 3 for top-three results.",
                key="filter_places",
            )

            enable_bracket_filter = st.checkbox(
                "Enable Bracket Number filter",
                value=False,
                key="enable_bracket_filter",
            )

            filter_bracket_from = st.number_input(
                "From Bracket Number (枠番)",
                min_value=1,
                max_value=8,
                value=1,
                key="filter_bracket_from",
            )

            filter_bracket_to = st.number_input(
                "To Bracket Number (枠番)",
                min_value=1,
                max_value=8,
                value=8,
                key="filter_bracket_to",
            )

            enable_horse_filter = st.checkbox(
                "Enable Horse Number filter",
                value=False,
                key="enable_horse_filter",
            )

            filter_horse_from = st.number_input(
                "From Horse Number (馬番)",
                min_value=1,
                max_value=18,
                value=1,
                key="filter_horse_from",
            )

            filter_horse_to = st.number_input(
                "To Horse Number (馬番)",
                min_value=1,
                max_value=18,
                value=18,
                key="filter_horse_to",
            )

            enable_weight_filter = st.checkbox(
                "Enable Horse Weight filter",
                value=False,
                key="enable_weight_filter",
            )

            filter_weight_from = st.number_input(
                "From Horse Weight (kg)",
                min_value=0.0,
                max_value=999.9,
                value=0.0,
                step=0.1,
                key="filter_weight_from",
            )

            filter_weight_to = st.number_input(
                "To Horse Weight (kg)",
                min_value=0.0,
                max_value=999.9,
                value=999.9,
                step=0.1,
                key="filter_weight_to",
            )

    selected_filters = {
        "horse_id": get_selected_id(horse_ids, filter_horse_idx),
        "jockey_id": get_selected_id(jockey_ids, filter_jockey_idx),
        "previous_jockey_id": get_selected_id(
            jockey_ids,
            filter_previous_jockey_idx,
        ),
        "trainer_id": get_selected_id(trainer_ids, filter_trainer_idx),
        "breeding_farm_id": get_selected_id(
            breeding_farm_ids,
            filter_breeding_farm_idx,
        ),
        "stallion_id": get_selected_id(
            stallion_ids,
            filter_stallion_idx,
        ),
        "broodmare_sire_id": get_selected_id(
            stallion_ids,
            filter_broodmare_sire_idx,
        ),
        "venue_id": get_selected_id(venue_ids, filter_venue_idx),
        "race_name_id": get_selected_id(race_ids, filter_race_idx),
    }

    filtered_checklists = filter_checklists(
        checklists=checklists,
        selected_filters=selected_filters,
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

    if not filtered_checklists:
        st.info("No checklists found with the selected filters.")
        return

    metrics = calculate_review_metrics(filtered_checklists)

    st.subheader("Results Summary")

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    metric_col1.metric("Filtered races", metrics["total"])
    metric_col2.metric(
        "Completed results",
        metrics["completed"],
    )
    metric_col3.metric(
        "Top 3 rate",
        (
            f"{metrics['top_3_rate']:.1f}%"
            if metrics["top_3_rate"] is not None
            else "-"
        ),
    )
    metric_col4.metric(
        "Win rate",
        (
            f"{metrics['win_rate']:.1f}%"
            if metrics["win_rate"] is not None
            else "-"
        ),
    )

    st.caption(
        "Average odds among top-three finishes: "
        + (
            f"{metrics['average_top_3_odds']:.2f}"
            if metrics["average_top_3_odds"] is not None
            else "-"
        )
        + " | Average prize among top-five finishes: "
        + (
            f"{metrics['average_top_5_prize']:,.0f}"
            if metrics["average_top_5_prize"] is not None
            else "-"
        )
    )

    st.subheader("Download Filtered Results")

    download_col1, download_col2 = st.columns(2)

    with download_col1:
        st.download_button(
            label="📥 Download CSV (UTF-8 BOM)",
            data=build_csv_download_bytes(
                filtered_checklists,
                encoding="utf-8-sig",
            ),
            file_name="filtered_checklists_utf8.csv",
            mime="text/csv",
        )

    with download_col2:
        st.download_button(
            label="📥 Download CSV (Shift-JIS)",
            data=build_csv_download_bytes(
                filtered_checklists,
                encoding="shift_jis",
            ),
            file_name="filtered_checklists_sjis.csv",
            mime="text/csv",
        )

    st.markdown("---")
    st.subheader("Results List")

    page_size = st.selectbox(
        "Items per page",
        [10, 20, 50],
        index=1,
        key="review_page_size",
    )

    total_results = len(filtered_checklists)
    total_pages = max(1, (total_results + page_size - 1) // page_size)

    page_options = list(range(1, total_pages + 1))

    selected_page = st.selectbox(
        "Page",
        page_options,
        key="review_page_number",
    )

    start_index = (selected_page - 1) * page_size
    end_index = min(start_index + page_size, total_results)
    paged_checklists = filtered_checklists[start_index:end_index]

    st.caption(
        f"Showing {start_index + 1}-{end_index} of {total_results} checklist(s)"
    )

    st.dataframe(
        build_summary_dataframe(paged_checklists),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("Select One Checklist to Edit")

    # THIS IS THE MAIN STABILITY FIX:
    # Only one detailed editor is rendered, regardless of page size.
    # The old code rendered full forms for every checklist on the current page.
    checklist_lookup = {entry["id"]: entry for entry in paged_checklists}

    def format_checklist_choice(checklist_id):
        entry = checklist_lookup[checklist_id]

        return (
            f"#{entry['id']} | {entry.get('date_of_race') or '-'} | "
            f"{entry.get('horse_name') or '-'} | "
            f"{entry.get('race_name') or '-'} | "
            f"Place: {entry.get('finished_place') or '-'}"
        )

    available_ids = list(checklist_lookup.keys())

    if "selected_review_checklist_id" not in st.session_state:
        st.session_state.selected_review_checklist_id = available_ids[0]

    if st.session_state.selected_review_checklist_id not in available_ids:
        st.session_state.selected_review_checklist_id = available_ids[0]

    selected_review_checklist_id = st.selectbox(
        "Checklist",
        available_ids,
        format_func=format_checklist_choice,
        key="selected_review_checklist_id",
    )

    selected_entry = checklist_lookup[selected_review_checklist_id]

    render_checklist_editor(
        entry=selected_entry,
        owner_id=owner_id,
        horses=horses,
        jockeys=jockeys,
        trainers=trainers,
        breeding_farms=breeding_farms,
        stallions=stallions,
        venues=venues,
        race_names=race_names,
        criteria=criteria,
    )


# -------------------------------------------------
# App
# -------------------------------------------------
init_db()

st.title("🐎 Horse Checklist App")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.display_name = ""
    st.session_state.user_id = None

if st.session_state.logged_in:
    st.sidebar.write(f"Logged in as: {st.session_state.display_name}")

    page = st.sidebar.radio(
        "Menu",
        [
            "Register Horse (Template)",
            "Register Jockey (Template)",
            "Register Trainer (Template)",
            "Register Breeding Farm (Template)",
            "Register Stallion (Template)",
            "Register Venue (Template)",
            "Register Race Name (Template)",
            "Register Criteria (Template)",
            "Race Checklist",
            "Checklist Review",
        ],
    )

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.display_name = ""
        st.session_state.user_id = None
        st.session_state.pop("selected_review_checklist_id", None)
        st.rerun()

    if page == "Register Horse (Template)":
        render_template_page(
            "horse",
            "Register a Horse Template",
            "Horse Name",
        )

    elif page == "Register Jockey (Template)":
        render_template_page(
            "jockey",
            "Register a Jockey Template",
            "Jockey Name",
        )

    elif page == "Register Trainer (Template)":
        render_template_page(
            "trainer",
            "Register a Trainer Template",
            "Trainer Name",
        )

    elif page == "Register Breeding Farm (Template)":
        render_template_page(
            "breeding_farm",
            "Register a Breeding Farm Template",
            "Breeding Farm Name",
        )

    elif page == "Register Stallion (Template)":
        render_template_page(
            "stallion",
            "Register a Stallion Template",
            "Stallion Name",
        )

    elif page == "Register Venue (Template)":
        render_template_page(
            "venue",
            "Register a Venue (Racecourse) Template",
            "Venue Name (e.g., Tokyo)",
        )

    elif page == "Register Race Name (Template)":
        render_template_page(
            "race_name",
            "Register a Race Name Template",
            "Race Name",
        )

    elif page == "Register Criteria (Template)":
        render_template_page(
            "criteria",
            "Register Checklist Criteria Template",
            "Criteria Name (e.g., Won Previous Race)",
        )

    elif page == "Race Checklist":
        render_race_checklist_page()

    elif page == "Checklist Review":
        render_checklist_review_page()

else:
    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        st.header("Login")

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_clicked = st.form_submit_button("Login")

        if login_clicked:
            if not clean_text(username) or not password:
                st.error("Please fill all fields.")
            else:
                success, display_name, user_id = login_user(
                    clean_text(username),
                    password,
                )

                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = clean_text(username)
                    st.session_state.display_name = display_name
                    st.session_state.user_id = user_id
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

    with register_tab:
        st.header("Register")

        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Username")
            display_name = st.text_input("Display Name")
            password = st.text_input("Password", type="password")
            invitation_code = st.text_input("Invitation Code")
            register_clicked = st.form_submit_button("Register")

        if register_clicked:
            if (
                not clean_text(username)
                or not clean_text(display_name)
                or not password
                or not clean_text(invitation_code)
            ):
                st.error("Please fill all fields.")
            else:
                success, message = register_user(
                    clean_text(username),
                    clean_text(display_name),
                    password,
                    clean_text(invitation_code),
                )

                if success:
                    st.success(message)
                else:
                    st.error(message)
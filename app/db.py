"""Database layer for HumanOptimizer.

Supports two modes:
  1. Local SQLite (default) — no config needed
  2. Supabase Postgres — set DATABASE_URL env var

All SQL uses ? placeholders. When using Postgres, they're converted to %s automatically.
"""

import os
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "humanoptimizer.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")
IS_POSTGRES = DATABASE_URL.startswith("postgres")


def get_connection():
    """Get a database connection."""
    if IS_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return _PgConnectionWrapper(conn)

    # Local SQLite
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class _PgConnectionWrapper:
    """Wraps psycopg2 connection to be compatible with SQLite-style code.

    - Converts ? placeholders to %s
    - Converts INSERT OR REPLACE to Postgres UPSERT
    - Returns dict rows
    """

    def __init__(self, conn):
        self._conn = conn

    def _convert_sql(self, sql):
        """Convert SQLite SQL to Postgres-compatible SQL."""
        # ? -> %s
        sql = sql.replace("?", "%s")
        # datetime('now') -> NOW()
        sql = sql.replace("datetime('now')", "NOW()")
        # INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
        sql = re.sub(r'INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY', sql, flags=re.IGNORECASE)
        # INTEGER PRIMARY KEY CHECK (id = 1) -> INTEGER PRIMARY KEY CHECK (id = 1)  (same in PG)
        # INSERT OR REPLACE -> INSERT ... ON CONFLICT
        sql = self._convert_upsert(sql)
        return sql

    def _convert_upsert(self, sql):
        """Convert INSERT OR REPLACE INTO table (...) VALUES (...) to Postgres upsert."""
        match = re.match(
            r'\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)',
            sql, re.IGNORECASE | re.DOTALL
        )
        if not match:
            return sql

        table = match.group(1)
        columns = match.group(2)
        values = match.group(3)

        # Determine the primary key for each table
        pk_map = {
            "daily_logs": "date",
            "power_list": "date",
            "seven_five_hard": "date",
            "weekly_summaries": "week_start",
            "whoop_daily": "date",
            "whoop_tokens": "id",
            "daily_scores": "date",
        }
        pk = pk_map.get(table)

        if pk:
            col_list = [c.strip() for c in columns.split(",")]
            update_cols = [c for c in col_list if c != pk]
            update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            return f"INSERT INTO {table} ({columns}) VALUES ({values}) ON CONFLICT ({pk}) DO UPDATE SET {update_clause}"

        return sql.replace("INSERT OR REPLACE", "INSERT")

    def execute(self, sql, params=None):
        import psycopg2.extras
        sql = self._convert_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
        except Exception as e:
            self._conn.rollback()
            raise
        return _PgCursorWrapper(cur)

    def executescript(self, sql):
        """Execute multiple statements."""
        import psycopg2.extras
        sql = self._convert_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        self._conn.commit()
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _PgCursorWrapper:
    """Wraps psycopg2 cursor to return dict-compatible rows."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        try:
            rows = self._cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def __getitem__(self, key):
        """Support cursor[0] for last_insert_rowid() results."""
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return list(row.values())[key]
        return row[key]


def sync_if_turso(conn):
    """No-op for Postgres. Kept for backward compatibility."""
    pass


# Schema — compatible with both SQLite and Postgres
SCHEMA_SQLITE = """
    CREATE TABLE IF NOT EXISTS daily_logs (
        date TEXT PRIMARY KEY,
        weight REAL,
        fasting_day INTEGER DEFAULT 0,
        fasting_cycle_day INTEGER DEFAULT 1,
        day_type TEXT DEFAULT 'Upper',
        recovery INTEGER,
        strain INTEGER,
        sleep_score INTEGER,
        rhr INTEGER,
        hrv INTEGER,
        walk_minutes INTEGER DEFAULT 0,
        vest_weight REAL DEFAULT 0,
        communication_minutes INTEGER DEFAULT 0,
        communication_sessions INTEGER DEFAULT 0,
        communication_notes TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS power_list (
        date TEXT PRIMARY KEY,
        task1_name TEXT DEFAULT 'Gym Workout',
        task1_done INTEGER DEFAULT 0,
        task2_name TEXT DEFAULT 'Outdoor Walk',
        task2_done INTEGER DEFAULT 0,
        task3_name TEXT DEFAULT 'Communication Practice',
        task3_done INTEGER DEFAULT 0,
        task4_name TEXT DEFAULT 'Reading / Reflection',
        task4_done INTEGER DEFAULT 0,
        task5_name TEXT DEFAULT 'Custom Task',
        task5_done INTEGER DEFAULT 0,
        completed_count INTEGER DEFAULT 0,
        result TEXT DEFAULT 'PENDING'
    );

    CREATE TABLE IF NOT EXISTS seven_five_hard (
        date TEXT PRIMARY KEY,
        workout1 INTEGER DEFAULT 0,
        workout2_outdoor INTEGER DEFAULT 0,
        reading_10_pages INTEGER DEFAULT 0,
        water_gallon INTEGER DEFAULT 0,
        diet_followed INTEGER DEFAULT 0,
        progress_photo INTEGER DEFAULT 0,
        all_complete INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS weekly_summaries (
        week_start TEXT PRIMARY KEY,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0,
        weight_start REAL,
        weight_end REAL,
        weight_change REAL,
        streak INTEGER DEFAULT 0,
        gym_consistency REAL DEFAULT 0,
        walk_consistency REAL DEFAULT 0,
        communication_consistency REAL DEFAULT 0,
        summary TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS blood_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        test_name TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT DEFAULT '',
        reference_low REAL,
        reference_high REAL,
        flag TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS blood_test_panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        panel_name TEXT DEFAULT 'General',
        lab_name TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        workout_type TEXT DEFAULT 'strength',
        exercises TEXT NOT NULL,
        duration_minutes INTEGER,
        intensity INTEGER,
        energy_level INTEGER,
        heart_rate_avg INTEGER,
        heart_rate_max INTEGER,
        notes TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS whoop_daily (
        date TEXT PRIMARY KEY,
        recovery_score INTEGER,
        hrv REAL,
        rhr INTEGER,
        spo2 REAL,
        skin_temp REAL,
        sleep_score INTEGER,
        sleep_hours REAL,
        sleep_efficiency REAL,
        sleep_consistency REAL,
        rem_hours REAL,
        deep_sleep_hours REAL,
        light_sleep_hours REAL,
        time_in_bed_hours REAL,
        disturbances INTEGER,
        sleep_cycles INTEGER,
        sleep_needed_hours REAL,
        sleep_debt_hours REAL,
        respiratory_rate REAL,
        strain REAL,
        calories_burned INTEGER,
        avg_hr INTEGER,
        max_hr INTEGER,
        raw_json TEXT DEFAULT '',
        synced_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS whoop_tokens (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        scopes TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        target_value REAL,
        target_unit TEXT DEFAULT '',
        target_date TEXT,
        current_value REAL DEFAULT 0,
        status TEXT DEFAULT 'active',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS goal_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goal_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        value REAL NOT NULL,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (goal_id) REFERENCES goals(id)
    );

    CREATE TABLE IF NOT EXISTS power_list_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot INTEGER NOT NULL,
        task_name TEXT NOT NULL,
        is_default INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS daily_routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL DEFAULT 'default',
        schedule TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS daily_scores (
        date TEXT PRIMARY KEY,
        power_list_score REAL DEFAULT 0,
        discipline_score REAL DEFAULT 0,
        nutrition_score REAL DEFAULT 0,
        training_score REAL DEFAULT 0,
        recovery_score REAL DEFAULT 0,
        communication_score REAL DEFAULT 0,
        total_score REAL DEFAULT 0,
        grade TEXT DEFAULT '',
        wins TEXT DEFAULT '',
        losses TEXT DEFAULT '',
        lessons TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS twelve_week_years (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        goals TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS twelve_week_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        twelve_week_id INTEGER NOT NULL,
        week_number INTEGER NOT NULL,
        planned_actions INTEGER DEFAULT 0,
        completed_actions INTEGER DEFAULT 0,
        score REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (twelve_week_id) REFERENCES twelve_week_years(id)
    );

    CREATE TABLE IF NOT EXISTS meals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        meal_type TEXT DEFAULT 'omad',
        description TEXT DEFAULT '',
        calories INTEGER,
        protein_g REAL,
        carbs_g REAL,
        fat_g REAL,
        fiber_g REAL,
        foods TEXT DEFAULT '',
        photo_logged INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
"""

SCHEMA_POSTGRES = """
    CREATE TABLE IF NOT EXISTS daily_logs (
        date TEXT PRIMARY KEY, weight REAL, fasting_day INTEGER DEFAULT 0,
        fasting_cycle_day INTEGER DEFAULT 1, day_type TEXT DEFAULT 'Upper',
        recovery INTEGER, strain INTEGER, sleep_score INTEGER, rhr INTEGER, hrv INTEGER,
        walk_minutes INTEGER DEFAULT 0, vest_weight REAL DEFAULT 0,
        communication_minutes INTEGER DEFAULT 0, communication_sessions INTEGER DEFAULT 0,
        communication_notes TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS power_list (
        date TEXT PRIMARY KEY, task1_name TEXT DEFAULT 'Gym Workout', task1_done INTEGER DEFAULT 0,
        task2_name TEXT DEFAULT 'Outdoor Walk', task2_done INTEGER DEFAULT 0,
        task3_name TEXT DEFAULT 'Communication Practice', task3_done INTEGER DEFAULT 0,
        task4_name TEXT DEFAULT 'Reading / Reflection', task4_done INTEGER DEFAULT 0,
        task5_name TEXT DEFAULT 'Custom Task', task5_done INTEGER DEFAULT 0,
        completed_count INTEGER DEFAULT 0, result TEXT DEFAULT 'PENDING'
    );
    CREATE TABLE IF NOT EXISTS seven_five_hard (
        date TEXT PRIMARY KEY, workout1 INTEGER DEFAULT 0, workout2_outdoor INTEGER DEFAULT 0,
        reading_10_pages INTEGER DEFAULT 0, water_gallon INTEGER DEFAULT 0,
        diet_followed INTEGER DEFAULT 0, progress_photo INTEGER DEFAULT 0, all_complete INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS weekly_summaries (
        week_start TEXT PRIMARY KEY, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0, weight_start REAL, weight_end REAL, weight_change REAL,
        streak INTEGER DEFAULT 0, gym_consistency REAL DEFAULT 0, walk_consistency REAL DEFAULT 0,
        communication_consistency REAL DEFAULT 0, summary TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS blood_tests (
        id SERIAL PRIMARY KEY, date TEXT NOT NULL, test_name TEXT NOT NULL, value REAL NOT NULL,
        unit TEXT DEFAULT '', reference_low REAL, reference_high REAL, flag TEXT DEFAULT '',
        notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS blood_test_panels (
        id SERIAL PRIMARY KEY, date TEXT NOT NULL, panel_name TEXT DEFAULT 'General',
        lab_name TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS workouts (
        id SERIAL PRIMARY KEY, date TEXT NOT NULL, workout_type TEXT DEFAULT 'strength',
        exercises TEXT NOT NULL, duration_minutes INTEGER, intensity INTEGER, energy_level INTEGER,
        heart_rate_avg INTEGER, heart_rate_max INTEGER, notes TEXT DEFAULT '',
        source TEXT DEFAULT 'manual', created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS whoop_daily (
        date TEXT PRIMARY KEY, recovery_score INTEGER, hrv REAL, rhr INTEGER,
        spo2 REAL, skin_temp REAL,
        sleep_score INTEGER, sleep_hours REAL, sleep_efficiency REAL, sleep_consistency REAL,
        rem_hours REAL, deep_sleep_hours REAL, light_sleep_hours REAL, time_in_bed_hours REAL,
        disturbances INTEGER, sleep_cycles INTEGER, sleep_needed_hours REAL, sleep_debt_hours REAL,
        respiratory_rate REAL, strain REAL, calories_burned INTEGER,
        avg_hr INTEGER, max_hr INTEGER,
        raw_json TEXT DEFAULT '', synced_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS whoop_tokens (
        id INTEGER PRIMARY KEY CHECK (id = 1), access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL, expires_at TEXT NOT NULL, scopes TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS goals (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL, category TEXT DEFAULT 'general',
        target_value REAL, target_unit TEXT DEFAULT '', target_date TEXT,
        current_value REAL DEFAULT 0, status TEXT DEFAULT 'active', notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS goal_progress (
        id SERIAL PRIMARY KEY, goal_id INTEGER NOT NULL, date TEXT NOT NULL,
        value REAL NOT NULL, notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (goal_id) REFERENCES goals(id)
    );
    CREATE TABLE IF NOT EXISTS power_list_templates (
        id SERIAL PRIMARY KEY, slot INTEGER NOT NULL, task_name TEXT NOT NULL,
        is_default INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS daily_routines (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL DEFAULT 'default', schedule TEXT NOT NULL,
        active INTEGER DEFAULT 1, notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS daily_scores (
        date TEXT PRIMARY KEY, power_list_score REAL DEFAULT 0, discipline_score REAL DEFAULT 0,
        nutrition_score REAL DEFAULT 0, training_score REAL DEFAULT 0, recovery_score REAL DEFAULT 0,
        communication_score REAL DEFAULT 0, total_score REAL DEFAULT 0, grade TEXT DEFAULT '',
        wins TEXT DEFAULT '', losses TEXT DEFAULT '', lessons TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS twelve_week_years (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL, start_date TEXT NOT NULL,
        end_date TEXT NOT NULL, goals TEXT NOT NULL, status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS twelve_week_scores (
        id SERIAL PRIMARY KEY, twelve_week_id INTEGER NOT NULL, week_number INTEGER NOT NULL,
        planned_actions INTEGER DEFAULT 0, completed_actions INTEGER DEFAULT 0,
        score REAL DEFAULT 0, notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (twelve_week_id) REFERENCES twelve_week_years(id)
    );
    CREATE TABLE IF NOT EXISTS meals (
        id SERIAL PRIMARY KEY, date TEXT NOT NULL, meal_type TEXT DEFAULT 'omad',
        description TEXT DEFAULT '', calories INTEGER, protein_g REAL, carbs_g REAL,
        fat_g REAL, fiber_g REAL, foods TEXT DEFAULT '', photo_logged INTEGER DEFAULT 0,
        notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW()
    );
"""


def init_db():
    conn = get_connection()
    if IS_POSTGRES:
        conn.executescript(SCHEMA_POSTGRES)
    else:
        conn.executescript(SCHEMA_SQLITE)
    conn.commit()
    conn.close()

    mode = "Supabase Postgres" if IS_POSTGRES else "local SQLite"
    print(f"Database initialized — mode: {mode}")


if __name__ == "__main__":
    init_db()

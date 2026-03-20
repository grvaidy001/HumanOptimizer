"""Database setup and schema for HumanOptimizer.

Supports two modes:
  1. Local SQLite (default) — no config needed
  2. Turso cloud — set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars

When Turso env vars are not set, uses standard sqlite3 (no extra dependencies).
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "humanoptimizer.db"
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")


def get_connection():
    """Get a database connection. Uses sqlite3 for local, libsql for Turso."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if TURSO_URL and TURSO_TOKEN:
        try:
            import libsql
            conn = libsql.connect(
                str(DB_PATH),
                sync_url=TURSO_URL,
                auth_token=TURSO_TOKEN,
            )
            conn.sync()
            # libsql doesn't support row_factory — wrap it
            return _DictConnectionWrapper(conn, is_turso=True)
        except ImportError:
            pass

    # Default: local sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class _DictConnectionWrapper:
    """Wraps a libsql connection to return dict-like rows."""

    def __init__(self, conn, is_turso=False):
        self._conn = conn
        self._is_turso = is_turso

    def execute(self, sql, params=None):
        if params:
            cursor = self._conn.execute(sql, params)
        else:
            cursor = self._conn.execute(sql)
        return _DictCursorWrapper(cursor)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def sync(self):
        if self._is_turso and hasattr(self._conn, 'sync'):
            self._conn.sync()


class _DictCursorWrapper:
    """Wraps a libsql cursor to return dict rows."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._to_dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._to_dict(r) for r in rows]

    def _to_dict(self, row):
        if isinstance(row, dict):
            return row
        if hasattr(self._cursor, 'description') and self._cursor.description:
            columns = [col[0] for col in self._cursor.description]
            return dict(zip(columns, row))
        return row


def sync_if_turso(conn):
    """Call after writes to push changes to Turso cloud."""
    if hasattr(conn, 'sync'):
        conn.sync()


SCHEMA = """
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
        sleep_score INTEGER,
        sleep_hours REAL,
        strain REAL,
        calories_burned INTEGER,
        avg_hr INTEGER,
        max_hr INTEGER,
        respiratory_rate REAL,
        spo2 REAL,
        skin_temp REAL,
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


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    mode = "Turso (embedded replica)" if (TURSO_URL and TURSO_TOKEN) else "local SQLite"
    print(f"Database initialized — mode: {mode}, path: {DB_PATH}")


if __name__ == "__main__":
    init_db()

"""HumanOptimizer MCP Server for Claude Desktop.

Exposes daily tracking, power list, coaching, blood work, WHOOP persistence,
and weekly review as tools that Claude can call directly.

Supports both local (stdio) and remote (streamable-http) transport.
Set MCP_TRANSPORT=http and PORT=8000 for remote deployment.
"""

import sys
import os
import json
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env file if it exists (local dev)
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

from app.db import init_db, get_connection, sync_if_turso
from app.coach import generate_daily_plan
from app.models import CoachingInput

init_db()

# Remote mode: stateless HTTP for cloud deployment
IS_REMOTE = os.getenv("MCP_TRANSPORT", "stdio") == "http"
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME", "humanoptimizer.onrender.com")

# Allow the Render hostname when running remotely
transport_security = None
if IS_REMOTE:
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )

mcp = FastMCP(
    "HumanOptimizer",
    stateless_http=IS_REMOTE,
    host="0.0.0.0" if IS_REMOTE else "127.0.0.1",
    transport_security=transport_security,
    instructions="""You are connected to HumanOptimizer — a personal execution system.

The user is on an aggressive fat loss journey (~350 lbs, goal: lose 100+ lbs).
They follow a rolling 72-hour fasting protocol:
  Day 1: FAST, Day 2: FAST, Day 3: FAST, Day 4: REFEED

They train daily: strength, sled work, 45 min walking, weighted vest.
They track 5 critical daily tasks (Power List) — 5/5 = WIN, <5 = LOSS.
They also do 75 Hard and practice communication skills.
They track weekly blood work to monitor health markers during aggressive fat loss.

Use the tools below to log data, check status, and provide coaching.
Always be direct and action-oriented. This user wants structure, not motivation."""
)


# ============================================================
# TODAY / DASHBOARD
# ============================================================

@mcp.tool()
def get_today() -> dict:
    """Get today's complete status: power list, daily log, 75 Hard, streak, and stats."""
    today = date.today().isoformat()
    conn = get_connection()

    pl = conn.execute("SELECT * FROM power_list WHERE date = ?", (today,)).fetchone()
    dl = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (today,)).fetchone()
    sh = conn.execute("SELECT * FROM seven_five_hard WHERE date = ?", (today,)).fetchone()
    whoop = conn.execute("SELECT * FROM whoop_daily WHERE date = ?", (today,)).fetchone()

    rows = conn.execute("SELECT result FROM power_list ORDER BY date DESC").fetchall()
    streak = 0
    for r in rows:
        if r["result"] == "WIN":
            streak += 1
        else:
            break

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    stats_rows = conn.execute(
        "SELECT result, COUNT(*) as cnt FROM power_list WHERE date >= ? GROUP BY result",
        (cutoff,)
    ).fetchall()
    wins = sum(r["cnt"] for r in stats_rows if r["result"] == "WIN")
    losses = sum(r["cnt"] for r in stats_rows if r["result"] == "LOSS")
    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    conn.close()

    return {
        "date": today,
        "power_list": dict(pl) if pl else None,
        "daily_log": dict(dl) if dl else None,
        "seven_five_hard": dict(sh) if sh else None,
        "whoop": dict(whoop) if whoop else None,
        "streak": streak,
        "win_rate": win_rate,
        "wins_30d": wins,
        "losses_30d": losses,
    }


@mcp.tool()
def get_date_log(target_date: str) -> dict:
    """Get all data for a specific date. Format: YYYY-MM-DD."""
    conn = get_connection()
    pl = conn.execute("SELECT * FROM power_list WHERE date = ?", (target_date,)).fetchone()
    dl = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (target_date,)).fetchone()
    sh = conn.execute("SELECT * FROM seven_five_hard WHERE date = ?", (target_date,)).fetchone()
    whoop = conn.execute("SELECT * FROM whoop_daily WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    return {
        "date": target_date,
        "power_list": dict(pl) if pl else None,
        "daily_log": dict(dl) if dl else None,
        "seven_five_hard": dict(sh) if sh else None,
        "whoop": dict(whoop) if whoop else None,
    }


# ============================================================
# POWER LIST
# ============================================================

@mcp.tool()
def save_power_list(
    task1_done: bool = False,
    task2_done: bool = False,
    task3_done: bool = False,
    task4_done: bool = False,
    task5_done: bool = False,
    task1_name: str = "Gym Workout",
    task2_name: str = "Outdoor Walk",
    task3_name: str = "Communication Practice",
    task4_name: str = "Reading / Reflection",
    task5_name: str = "Custom Task",
    target_date: str = "",
) -> dict:
    """Save or update today's Power List. 5/5 = WIN, <5 = LOSS.

    Default tasks: Gym Workout, Outdoor Walk, Communication Practice, Reading/Reflection, Custom Task.
    """
    d = target_date or date.today().isoformat()
    tasks = [task1_done, task2_done, task3_done, task4_done, task5_done]
    completed = sum(tasks)
    result = "WIN" if completed == 5 else "LOSS" if completed > 0 else "PENDING"

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO power_list
        (date, task1_name, task1_done, task2_name, task2_done, task3_name, task3_done,
         task4_name, task4_done, task5_name, task5_done, completed_count, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, task1_name, int(task1_done), task2_name, int(task2_done),
          task3_name, int(task3_done), task4_name, int(task4_done),
          task5_name, int(task5_done), completed, result))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {"date": d, "completed": completed, "result": result, "tasks": {
        task1_name: task1_done, task2_name: task2_done, task3_name: task3_done,
        task4_name: task4_done, task5_name: task5_done,
    }}


@mcp.tool()
def mark_task_done(task_number: int, target_date: str = "") -> dict:
    """Mark a single Power List task as done (1-5). Creates the list if it doesn't exist."""
    d = target_date or date.today().isoformat()
    conn = get_connection()

    row = conn.execute("SELECT * FROM power_list WHERE date = ?", (d,)).fetchone()
    if not row:
        conn.execute("INSERT INTO power_list (date) VALUES (?)", (d,))
        conn.commit()
        row = conn.execute("SELECT * FROM power_list WHERE date = ?", (d,)).fetchone()

    col = f"task{task_number}_done"
    if col not in dict(row):
        conn.close()
        return {"error": f"Invalid task number {task_number}. Must be 1-5."}

    conn.execute(f"UPDATE power_list SET {col} = 1 WHERE date = ?", (d,))

    updated = conn.execute("SELECT * FROM power_list WHERE date = ?", (d,)).fetchone()
    completed = sum(updated[f"task{i}_done"] for i in range(1, 6))
    result = "WIN" if completed == 5 else "LOSS" if completed > 0 else "PENDING"
    conn.execute("UPDATE power_list SET completed_count = ?, result = ? WHERE date = ?",
                 (completed, result, d))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {"date": d, "task": task_number, "completed": completed, "result": result}


# ============================================================
# DAILY LOG
# ============================================================

@mcp.tool()
def log_daily(
    weight: float = None,
    fasting_day: bool = False,
    fasting_cycle_day: int = 1,
    day_type: str = "Upper",
    recovery: int = None,
    strain: int = None,
    sleep_score: int = None,
    rhr: int = None,
    hrv: int = None,
    walk_minutes: int = 0,
    vest_weight: float = 0,
    communication_minutes: int = 0,
    communication_sessions: int = 0,
    communication_notes: str = "",
    notes: str = "",
    target_date: str = "",
) -> dict:
    """Log daily metrics: weight, fasting status, recovery, training, walking, communication.

    day_type options: 'Upper', 'Lower + Sled', 'Recovery', 'Refeed/Heavy'
    fasting_cycle_day: 1-4 (1-3 = fast days, 4 = refeed)
    """
    d = target_date or date.today().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO daily_logs
        (date, weight, fasting_day, fasting_cycle_day, day_type, recovery, strain,
         sleep_score, rhr, hrv, walk_minutes, vest_weight, communication_minutes,
         communication_sessions, communication_notes, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, weight, int(fasting_day), fasting_cycle_day, day_type, recovery, strain,
          sleep_score, rhr, hrv, walk_minutes, vest_weight, communication_minutes,
          communication_sessions, communication_notes, notes))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {"date": d, "status": "logged", "weight": weight, "day_type": day_type,
            "fasting_cycle_day": fasting_cycle_day}


@mcp.tool()
def log_weight(weight: float, target_date: str = "") -> dict:
    """Quick log just weight for today."""
    d = target_date or date.today().isoformat()
    conn = get_connection()

    existing = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (d,)).fetchone()
    if existing:
        conn.execute("UPDATE daily_logs SET weight = ? WHERE date = ?", (weight, d))
    else:
        conn.execute("INSERT INTO daily_logs (date, weight) VALUES (?, ?)", (d, weight))

    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"date": d, "weight": weight}


@mcp.tool()
def get_weight_history(days: int = 30) -> list:
    """Get weight entries for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, weight FROM daily_logs WHERE date >= ? AND weight IS NOT NULL ORDER BY date",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# WORKOUT LOGGING
# ============================================================

@mcp.tool()
def log_workout(
    exercises: str,
    workout_type: str = "strength",
    duration_minutes: int = None,
    intensity: int = None,
    energy_level: int = None,
    heart_rate_avg: int = None,
    heart_rate_max: int = None,
    notes: str = "",
    source: str = "manual",
    target_date: str = "",
) -> dict:
    """Log a workout. Use this when the user provides a workout journal photo or describes their session.

    exercises should be a JSON string of exercises, e.g.:
    [
        {"name": "Leg Press", "sets": [{"reps": 12, "weight": 180}, {"reps": 10, "weight": 200}]},
        {"name": "Chest Press", "sets": [{"reps": 10, "weight": 100}, {"reps": 8, "weight": 110}]},
        {"name": "Lat Pulldown", "sets": [{"reps": 12, "weight": 90}]}
    ]

    workout_type: 'strength', 'cardio', 'sled', 'walk', 'mixed'
    intensity: 1-10 (RPE)
    energy_level: 1-10
    source: 'manual', 'photo', 'hevy'
    """
    d = target_date or date.today().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO workouts (date, workout_type, exercises, duration_minutes, intensity,
                              energy_level, heart_rate_avg, heart_rate_max, notes, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, workout_type, exercises, duration_minutes, intensity,
          energy_level, heart_rate_avg, heart_rate_max, notes, source))
    conn.commit()
    sync_if_turso(conn)

    total_sets = 0
    total_volume = 0
    try:
        ex_list = json.loads(exercises)
        for ex in ex_list:
            for s in ex.get("sets", []):
                total_sets += 1
                total_volume += s.get("reps", 0) * s.get("weight", 0)
    except (json.JSONDecodeError, TypeError):
        pass

    conn.close()
    return {
        "date": d,
        "workout_type": workout_type,
        "total_sets": total_sets,
        "total_volume": total_volume,
        "intensity": intensity,
        "source": source,
    }


@mcp.tool()
def get_workout_history(days: int = 30) -> list:
    """Get workout history for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE date >= ? ORDER BY date DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 75 HARD
# ============================================================

@mcp.tool()
def save_75_hard(
    workout1: bool = False,
    workout2_outdoor: bool = False,
    reading_10_pages: bool = False,
    water_gallon: bool = False,
    diet_followed: bool = False,
    progress_photo: bool = False,
    target_date: str = "",
) -> dict:
    """Save 75 Hard daily checklist. All 6 must be true for a complete day."""
    d = target_date or date.today().isoformat()
    all_complete = all([workout1, workout2_outdoor, reading_10_pages,
                        water_gallon, diet_followed, progress_photo])

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO seven_five_hard
        (date, workout1, workout2_outdoor, reading_10_pages, water_gallon,
         diet_followed, progress_photo, all_complete)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, int(workout1), int(workout2_outdoor), int(reading_10_pages),
          int(water_gallon), int(diet_followed), int(progress_photo), int(all_complete)))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    completed = sum([workout1, workout2_outdoor, reading_10_pages,
                     water_gallon, diet_followed, progress_photo])
    return {"date": d, "completed": f"{completed}/6", "all_complete": all_complete}


@mcp.tool()
def get_75_hard_streak() -> dict:
    """Get current 75 Hard streak (consecutive days with all 6 tasks complete)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, all_complete FROM seven_five_hard ORDER BY date DESC"
    ).fetchall()
    conn.close()

    streak = 0
    for r in rows:
        if r["all_complete"]:
            streak += 1
        else:
            break

    return {"streak": streak, "goal": 75, "remaining": max(0, 75 - streak)}


# ============================================================
# BLOOD WORK
# ============================================================

@mcp.tool()
def log_blood_test(
    test_name: str,
    value: float,
    unit: str = "",
    reference_low: float = None,
    reference_high: float = None,
    notes: str = "",
    target_date: str = "",
) -> dict:
    """Log a single blood test result.

    Common tests to track during aggressive fat loss:
    - Testosterone (ng/dL, ref: 300-1000)
    - Free T (pg/mL, ref: 8.7-25.1)
    - TSH (mIU/L, ref: 0.4-4.0)
    - T3 Free (pg/mL, ref: 2.0-4.4)
    - T4 Free (ng/dL, ref: 0.8-1.8)
    - CRP (mg/L, ref: 0-3.0)
    - Fasting Glucose (mg/dL, ref: 70-100)
    - Insulin (uIU/mL, ref: 2.6-24.9)
    - HbA1c (%, ref: 4.0-5.6)
    - Lipid Panel: Total Cholesterol, LDL, HDL, Triglycerides
    - Liver: AST, ALT, GGT
    - Kidney: BUN, Creatinine, eGFR
    - CBC: WBC, RBC, Hemoglobin, Hematocrit
    - Vitamin D (ng/mL, ref: 30-100)
    - Iron, Ferritin
    - Cortisol (mcg/dL, ref: 6-23)
    """
    d = target_date or date.today().isoformat()

    flag = ""
    if reference_low is not None and value < reference_low:
        flag = "LOW"
    elif reference_high is not None and value > reference_high:
        flag = "HIGH"

    conn = get_connection()
    conn.execute("""
        INSERT INTO blood_tests (date, test_name, value, unit, reference_low, reference_high, flag, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, test_name, value, unit, reference_low, reference_high, flag, notes))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {"date": d, "test": test_name, "value": value, "unit": unit, "flag": flag}


@mcp.tool()
def log_blood_panel(
    results: str,
    panel_name: str = "General",
    lab_name: str = "",
    notes: str = "",
    target_date: str = "",
) -> dict:
    """Log a full blood test panel with multiple results at once.

    results should be a JSON string of test results, e.g.:
    [
        {"name": "Testosterone", "value": 450, "unit": "ng/dL", "ref_low": 300, "ref_high": 1000},
        {"name": "TSH", "value": 2.1, "unit": "mIU/L", "ref_low": 0.4, "ref_high": 4.0},
        {"name": "Fasting Glucose", "value": 95, "unit": "mg/dL", "ref_low": 70, "ref_high": 100}
    ]
    """
    d = target_date or date.today().isoformat()
    conn = get_connection()

    conn.execute("""
        INSERT INTO blood_test_panels (date, panel_name, lab_name, notes)
        VALUES (?, ?, ?, ?)
    """, (d, panel_name, lab_name, notes))
    conn.commit()

    try:
        tests = json.loads(results)
    except json.JSONDecodeError:
        conn.close()
        return {"error": "Invalid JSON in results. See tool description for format."}

    logged = []
    for t in tests:
        name = t.get("name", "")
        value = t.get("value", 0)
        unit = t.get("unit", "")
        ref_low = t.get("ref_low")
        ref_high = t.get("ref_high")
        test_notes = t.get("notes", "")

        flag = ""
        if ref_low is not None and value < ref_low:
            flag = "LOW"
        elif ref_high is not None and value > ref_high:
            flag = "HIGH"

        conn.execute("""
            INSERT INTO blood_tests (date, test_name, value, unit, reference_low, reference_high, flag, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (d, name, value, unit, ref_low, ref_high, flag, test_notes))

        logged.append({"test": name, "value": value, "unit": unit, "flag": flag})

    conn.commit()
    sync_if_turso(conn)
    conn.close()

    flagged = [t for t in logged if t["flag"]]
    return {
        "date": d,
        "panel": panel_name,
        "tests_logged": len(logged),
        "flagged": flagged,
        "all_results": logged,
    }


@mcp.tool()
def get_blood_test_history(test_name: str = "", days: int = 180) -> dict:
    """Get blood test history. If test_name is provided, shows trend for that specific test.
    Otherwise shows all recent results.
    """
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    if test_name:
        rows = conn.execute(
            "SELECT date, value, unit, flag, reference_low, reference_high FROM blood_tests WHERE test_name = ? AND date >= ? ORDER BY date",
            (test_name, cutoff)
        ).fetchall()
        conn.close()
        results = [dict(r) for r in rows]
        if results:
            values = [r["value"] for r in results]
            return {
                "test": test_name,
                "entries": results,
                "current": values[-1],
                "min": min(values),
                "max": max(values),
                "trend": "improving" if len(values) > 1 and values[-1] > values[0] else "declining" if len(values) > 1 else "single entry",
            }
        return {"test": test_name, "entries": [], "message": "No data found"}
    else:
        rows = conn.execute(
            "SELECT date, test_name, value, unit, flag FROM blood_tests WHERE date >= ? ORDER BY date DESC, test_name",
            (cutoff,)
        ).fetchall()
        conn.close()
        return {"entries": [dict(r) for r in rows]}


@mcp.tool()
def get_flagged_blood_results(days: int = 90) -> dict:
    """Get all blood test results that are out of range (HIGH or LOW)."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, test_name, value, unit, flag, reference_low, reference_high FROM blood_tests WHERE flag != '' AND date >= ? ORDER BY date DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return {"flagged_results": [dict(r) for r in rows], "count": len(rows)}


# ============================================================
# WHOOP DATA PERSISTENCE
# ============================================================

@mcp.tool()
def save_whoop_data(
    recovery_score: int = None,
    hrv: float = None,
    rhr: int = None,
    sleep_score: int = None,
    sleep_hours: float = None,
    strain: float = None,
    calories_burned: int = None,
    avg_hr: int = None,
    max_hr: int = None,
    respiratory_rate: float = None,
    spo2: float = None,
    skin_temp: float = None,
    raw_json: str = "",
    target_date: str = "",
) -> dict:
    """Save WHOOP data to local database for permanent storage.

    Use this AFTER pulling data from the WHOOP MCP server to persist it locally.
    This creates a historical record of all WHOOP metrics.
    """
    d = target_date or date.today().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO whoop_daily
        (date, recovery_score, hrv, rhr, sleep_score, sleep_hours, strain,
         calories_burned, avg_hr, max_hr, respiratory_rate, spo2, skin_temp, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, recovery_score, hrv, rhr, sleep_score, sleep_hours, strain,
          calories_burned, avg_hr, max_hr, respiratory_rate, spo2, skin_temp, raw_json))
    conn.commit()

    # Also update daily_logs with WHOOP data if a log exists
    existing = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (d,)).fetchone()
    if existing:
        updates = []
        params = []
        if recovery_score is not None:
            updates.append("recovery = ?")
            params.append(recovery_score)
        if strain is not None:
            updates.append("strain = ?")
            params.append(int(strain))
        if sleep_score is not None:
            updates.append("sleep_score = ?")
            params.append(sleep_score)
        if rhr is not None:
            updates.append("rhr = ?")
            params.append(rhr)
        if hrv is not None:
            updates.append("hrv = ?")
            params.append(int(hrv))
        if updates:
            params.append(d)
            conn.execute(f"UPDATE daily_logs SET {', '.join(updates)} WHERE date = ?", params)
            conn.commit()

    sync_if_turso(conn)
    conn.close()

    return {
        "date": d,
        "saved": True,
        "recovery": recovery_score,
        "hrv": hrv,
        "strain": strain,
        "sleep": sleep_score,
    }


@mcp.tool()
def get_whoop_history(days: int = 30) -> list:
    """Get stored WHOOP data history for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM whoop_daily WHERE date >= ? ORDER BY date",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# COACHING
# ============================================================

@mcp.tool()
def get_coaching_plan(
    recovery: int = None,
    strain: int = None,
    fasting_day: bool = False,
    day_type: str = "Upper",
    previous_result: str = "PENDING",
    sleep_score: int = None,
    hrv: int = None,
) -> dict:
    """Generate a rule-based daily coaching plan based on recovery, fasting, and training state."""
    input_data = CoachingInput(
        recovery=recovery,
        strain=strain,
        fasting_day=fasting_day,
        day_type=day_type,
        previous_result=previous_result,
        sleep_score=sleep_score,
        hrv=hrv,
    )
    return generate_daily_plan(input_data)


# ============================================================
# WEEKLY REVIEW
# ============================================================

@mcp.tool()
def get_weekly_summary(week_start: str = "") -> dict:
    """Get weekly summary: wins/losses, weight change, streak, consistency, blood work alerts."""
    if week_start:
        ws = date.fromisoformat(week_start)
    else:
        today = date.today()
        ws = today - timedelta(days=today.weekday())

    we = ws + timedelta(days=6)
    conn = get_connection()

    pl_rows = conn.execute(
        "SELECT result FROM power_list WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()
    wins = sum(1 for r in pl_rows if r["result"] == "WIN")
    losses = sum(1 for r in pl_rows if r["result"] == "LOSS")
    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    weight_rows = conn.execute(
        "SELECT date, weight FROM daily_logs WHERE date BETWEEN ? AND ? AND weight IS NOT NULL ORDER BY date",
        (ws.isoformat(), we.isoformat())
    ).fetchall()
    weight_start = weight_rows[0]["weight"] if weight_rows else None
    weight_end = weight_rows[-1]["weight"] if weight_rows else None
    weight_change = round(weight_end - weight_start, 1) if weight_start and weight_end else None

    log_rows = conn.execute(
        "SELECT * FROM daily_logs WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()
    days = len(log_rows)
    walk_days = sum(1 for r in log_rows if r["walk_minutes"] and r["walk_minutes"] > 0)
    comm_days = sum(1 for r in log_rows if r["communication_minutes"] and r["communication_minutes"] > 0)

    sh_rows = conn.execute(
        "SELECT all_complete FROM seven_five_hard WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()
    hard_days = sum(1 for r in sh_rows if r["all_complete"])

    # Blood work alerts this week
    blood_flags = conn.execute(
        "SELECT test_name, value, unit, flag FROM blood_tests WHERE date BETWEEN ? AND ? AND flag != ''",
        (ws.isoformat(), we.isoformat())
    ).fetchall()

    # WHOOP averages this week
    whoop_rows = conn.execute(
        "SELECT recovery_score, hrv, strain, sleep_score FROM whoop_daily WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()
    whoop_avg = {}
    if whoop_rows:
        def avg(key):
            vals = [r[key] for r in whoop_rows if r[key] is not None]
            return round(sum(vals) / len(vals), 1) if vals else None
        whoop_avg = {
            "avg_recovery": avg("recovery_score"),
            "avg_hrv": avg("hrv"),
            "avg_strain": avg("strain"),
            "avg_sleep": avg("sleep_score"),
        }

    conn.close()

    return {
        "week": f"{ws.isoformat()} to {we.isoformat()}",
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "weight_start": weight_start,
        "weight_end": weight_end,
        "weight_change": weight_change,
        "days_logged": days,
        "walk_days": walk_days,
        "communication_days": comm_days,
        "seventy_five_hard_days": hard_days,
        "walk_consistency": round(walk_days / 7 * 100) if days > 0 else 0,
        "communication_consistency": round(comm_days / 7 * 100) if days > 0 else 0,
        "blood_work_flags": [dict(r) for r in blood_flags],
        "whoop_averages": whoop_avg,
    }


@mcp.tool()
def get_all_history(days: int = 90) -> dict:
    """Get full history for analysis: all data for the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()

    logs = conn.execute("SELECT * FROM daily_logs WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()
    pls = conn.execute("SELECT * FROM power_list WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()
    shs = conn.execute("SELECT * FROM seven_five_hard WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()
    blood = conn.execute("SELECT * FROM blood_tests WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()
    whoop = conn.execute("SELECT * FROM whoop_daily WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()

    conn.close()
    return {
        "daily_logs": [dict(r) for r in logs],
        "power_lists": [dict(r) for r in pls],
        "seventy_five_hard": [dict(r) for r in shs],
        "blood_tests": [dict(r) for r in blood],
        "whoop_daily": [dict(r) for r in whoop],
        "total_days": len(logs),
    }


# ============================================================
# WHOOP LIVE API (OAuth + fetch)
# ============================================================

@mcp.tool()
def whoop_start_auth() -> dict:
    """Start WHOOP OAuth flow. Returns a URL for the user to open in their browser.

    Before calling this, set env vars: WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET.
    Register your app at https://developer-dashboard.whoop.com
    Set redirect URI to: http://localhost:8000/whoop/callback
    """
    from app.providers.whoop import get_auth_url, CLIENT_ID
    if not CLIENT_ID:
        return {"error": "WHOOP_CLIENT_ID not set. Set it as an environment variable."}
    url = get_auth_url()
    return {"auth_url": url, "instruction": "Open this URL in your browser, log in to WHOOP, then give me the code from the redirect URL."}


@mcp.tool()
def whoop_complete_auth(code: str) -> dict:
    """Complete WHOOP OAuth by exchanging the authorization code for tokens.

    After the user logs in via the auth URL, WHOOP redirects to the callback URL
    with a ?code= parameter. Pass that code here.
    """
    from app.providers.whoop import exchange_code, save_tokens
    try:
        token_data = exchange_code(code)
        conn = get_connection()
        save_tokens(conn, token_data)
        sync_if_turso(conn)
        conn.close()
        return {"status": "connected", "message": "WHOOP connected successfully. You can now fetch data."}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whoop_fetch_today(target_date: str = "") -> dict:
    """Fetch today's WHOOP data (recovery, sleep, strain) from the API and save to DB.

    This pulls live data from WHOOP, saves it permanently, and returns it.
    """
    from app.providers.whoop import fetch_all_daily, is_connected
    d = target_date or date.today().isoformat()
    conn = get_connection()

    if not is_connected(conn):
        conn.close()
        return {"error": "WHOOP not connected. Run whoop_start_auth first."}

    data = fetch_all_daily(conn, d)
    if "error" in data:
        conn.close()
        return data

    # Persist all fields to whoop_daily table
    conn.execute("""
        INSERT OR REPLACE INTO whoop_daily
        (date, recovery_score, hrv, rhr, spo2, skin_temp,
         sleep_score, sleep_hours, sleep_efficiency, sleep_consistency,
         rem_hours, deep_sleep_hours, light_sleep_hours, time_in_bed_hours,
         disturbances, sleep_cycles, sleep_needed_hours, sleep_debt_hours,
         respiratory_rate, strain, calories_burned, avg_hr, max_hr, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, data.get("recovery_score"), data.get("hrv"), data.get("rhr"),
          data.get("spo2"), data.get("skin_temp"),
          data.get("sleep_performance"), data.get("sleep_hours"),
          data.get("sleep_efficiency"), data.get("sleep_consistency"),
          data.get("rem_hours"), data.get("deep_sleep_hours"),
          data.get("light_sleep_hours"), data.get("time_in_bed_hours"),
          data.get("disturbances"), data.get("sleep_cycles"),
          data.get("sleep_needed_hours"), data.get("sleep_debt_hours"),
          data.get("respiratory_rate"), data.get("strain"),
          data.get("calories_burned"), data.get("avg_hr"), data.get("max_hr"),
          json.dumps(data)))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return data


@mcp.tool()
def whoop_fetch_range(days: int = 10) -> dict:
    """Fetch WHOOP data for the last N days in bulk and save to DB.

    For large ranges (30+ days), fetches in 2-week chunks to avoid timeouts.
    Max recommended: 30 days per call. For longer history, call multiple times.
    """
    from app.providers.whoop import fetch_bulk, is_connected
    conn = get_connection()

    if not is_connected(conn):
        conn.close()
        return {"error": "WHOOP not connected. Run whoop_start_auth first."}

    # Cap at 30 days to avoid timeout
    fetch_days = min(days, 30)
    records = fetch_bulk(conn, fetch_days)
    if records and "error" in records[0]:
        conn.close()
        return records[0]

    saved = []
    for data in records:
        d = data["date"]
        conn.execute("""
            INSERT OR REPLACE INTO whoop_daily
            (date, recovery_score, hrv, rhr, spo2, skin_temp,
             sleep_score, sleep_hours, sleep_efficiency, sleep_consistency,
             rem_hours, deep_sleep_hours, light_sleep_hours, time_in_bed_hours,
             disturbances, sleep_cycles, sleep_needed_hours, sleep_debt_hours,
             respiratory_rate, strain, calories_burned, avg_hr, max_hr, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d, data.get("recovery_score"), data.get("hrv"), data.get("rhr"),
              data.get("spo2"), data.get("skin_temp"),
              data.get("sleep_performance"), data.get("sleep_hours"),
              data.get("sleep_efficiency"), data.get("sleep_consistency"),
              data.get("rem_hours"), data.get("deep_sleep_hours"),
              data.get("light_sleep_hours"), data.get("time_in_bed_hours"),
              data.get("disturbances"), data.get("sleep_cycles"),
              data.get("sleep_needed_hours"), data.get("sleep_debt_hours"),
              data.get("respiratory_rate"), data.get("strain"),
              data.get("calories_burned"), data.get("avg_hr"), data.get("max_hr"),
              json.dumps(data)))
        saved.append({
            "date": d,
            "recovery": data.get("recovery_score"),
            "hrv": data.get("hrv"),
            "rhr": data.get("rhr"),
            "strain": data.get("strain"),
            "sleep_hours": data.get("sleep_hours"),
            "sleep_performance": data.get("sleep_performance"),
            "deep_sleep": data.get("deep_sleep_hours"),
            "rem": data.get("rem_hours"),
        })

    conn.commit()
    sync_if_turso(conn)
    conn.close()

    msg = f"Fetched {fetch_days} days." if days <= 30 else f"Fetched {fetch_days} of {days} days (max 30 per call). Call again for more."
    return {"days_saved": len(saved), "results": saved, "note": msg}


@mcp.tool()
def whoop_summary(days: int = 90) -> dict:
    """Get WHOOP summary/trends from STORED data (no API calls, instant).

    Use this for longer-term analysis. Data must be fetched first via whoop_fetch_range.
    Returns averages, trends, min/max for recovery, HRV, RHR, strain, sleep.
    """
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM whoop_daily WHERE date >= ? ORDER BY date", (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"message": f"No stored WHOOP data for last {days} days. Run whoop_fetch_range first."}

    data = [dict(r) for r in rows]

    def stats(key):
        vals = [d[key] for d in data if d.get(key) is not None]
        if not vals:
            return None
        return {
            "avg": round(sum(vals) / len(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
            "latest": round(vals[-1], 1),
            "first": round(vals[0], 1),
            "trend": "up" if len(vals) > 1 and vals[-1] > vals[0] else "down" if len(vals) > 1 and vals[-1] < vals[0] else "stable",
            "count": len(vals),
        }

    return {
        "period": f"Last {days} days",
        "days_with_data": len(data),
        "recovery": stats("recovery_score"),
        "hrv": stats("hrv"),
        "rhr": stats("rhr"),
        "strain": stats("strain"),
        "sleep_hours": stats("sleep_hours"),
        "sleep_score": stats("sleep_score"),
        "calories": stats("calories_burned"),
    }


@mcp.tool()
def whoop_debug() -> dict:
    """Debug WHOOP API — tests every endpoint path to find where sleep/recovery data lives.

    Tests: collection endpoints, per-cycle recovery, per-sleep-id, and raw responses.
    """
    from app.providers.whoop import _get_valid_token, _api_get, _paginate_all
    conn = get_connection()
    token = _get_valid_token(conn)
    conn.close()
    if not token:
        return {"error": "No valid token"}

    results = {}

    # 1. Get latest cycles (always works)
    cycle_data = _api_get(token, "/cycle", {"limit": 3})
    cycles = cycle_data.get("records", [])
    results["cycles"] = {"count": len(cycles), "ids": [c.get("id") for c in cycles]}

    # 2. Try collection endpoints
    for name, path in [("recovery_collection", "/recovery"), ("sleep_collection", "/activity/sleep")]:
        data = _api_get(token, path, {"limit": 3})
        records = data.get("records", [])
        results[name] = {"count": len(records), "has_data": bool(records)}
        if records:
            results[name]["first_record"] = records[0]

    # 3. Try per-cycle recovery (THE KEY TEST)
    if cycles:
        cycle_id = cycles[0]["id"]
        results["per_cycle_test"] = {"cycle_id": cycle_id}

        rec = _api_get(token, f"/cycle/{cycle_id}/recovery", {})
        results["per_cycle_test"]["recovery_raw"] = rec
        results["per_cycle_test"]["has_score"] = bool(rec.get("score"))

        # If recovery has sleep_id, fetch that sleep
        sleep_id = rec.get("sleep_id")
        if sleep_id:
            results["per_cycle_test"]["sleep_id"] = sleep_id
            slp = _api_get(token, f"/activity/sleep/{sleep_id}", {})
            results["per_cycle_test"]["sleep_raw"] = slp
            results["per_cycle_test"]["sleep_has_score"] = bool(slp.get("score"))
        else:
            results["per_cycle_test"]["sleep_id"] = None
            results["per_cycle_test"]["note"] = "No sleep_id in recovery response"

    # Also try profile
    try:
        profile = _api_get(token, "/user/profile/basic", {})
        results["profile"] = profile
    except Exception as e:
        results["profile"] = {"error": str(e)}

    return results


@mcp.tool()
def whoop_workouts(target_date: str = "", days: int = 7) -> dict:
    """Get WHOOP workout data with HR zones for analysis.

    Returns: sport type, strain, avg/max HR, calories, duration,
    and time spent in each HR zone (minutes).

    HR Zones: 0=<50%, 1=50-60%, 2=60-70%, 3=70-80%, 4=80-90%, 5=90-100% of max HR.
    Use for analyzing if training intensity matches recovery recommendations.
    """
    from app.providers.whoop import fetch_workouts, is_connected
    conn = get_connection()
    if not is_connected(conn):
        conn.close()
        return {"error": "WHOOP not connected"}

    d = target_date or date.today().isoformat()
    workouts = fetch_workouts(conn, d, days)
    conn.close()

    if workouts and "error" in workouts[0]:
        return workouts[0]

    return {"workouts": workouts, "count": len(workouts)}


@mcp.tool()
def whoop_status() -> dict:
    """Check if WHOOP is connected and tokens are valid."""
    from app.providers.whoop import is_connected, CLIENT_ID
    if not CLIENT_ID:
        return {"connected": False, "reason": "WHOOP_CLIENT_ID not configured"}
    conn = get_connection()
    connected = is_connected(conn)
    conn.close()
    return {"connected": connected}


@mcp.tool()
def whoop_get_refresh_token() -> dict:
    """Get the current WHOOP refresh token so you can save it as an env var.

    After connecting WHOOP, call this to get the refresh token.
    Then add WHOOP_REFRESH_TOKEN to your Render environment variables.
    This way WHOOP stays connected even after redeployments.
    """
    conn = get_connection()
    row = conn.execute("SELECT refresh_token FROM whoop_tokens WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return {"error": "No WHOOP tokens found. Connect WHOOP first."}
    return {
        "refresh_token": row["refresh_token"],
        "instruction": "Add this as WHOOP_REFRESH_TOKEN in your Render environment variables."
    }


# ============================================================
# POWER LIST CRUD
# ============================================================

@mcp.tool()
def set_power_list_tasks(
    task1: str = "Gym Workout",
    task2: str = "Outdoor Walk",
    task3: str = "Communication Practice",
    task4: str = "Reading / Reflection",
    task5: str = "Custom Task",
) -> dict:
    """Set the default Power List task names. These become the template for each new day."""
    conn = get_connection()
    conn.execute("DELETE FROM power_list_templates")
    for slot, name in enumerate([task1, task2, task3, task4, task5], 1):
        conn.execute("INSERT INTO power_list_templates (slot, task_name) VALUES (?, ?)", (slot, name))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"tasks": {1: task1, 2: task2, 3: task3, 4: task4, 5: task5}}


@mcp.tool()
def get_power_list_tasks() -> dict:
    """Get the current default Power List task names."""
    conn = get_connection()
    rows = conn.execute("SELECT slot, task_name FROM power_list_templates ORDER BY slot").fetchall()
    conn.close()
    if rows:
        return {"tasks": {r["slot"]: r["task_name"] for r in rows}}
    return {"tasks": {1: "Gym Workout", 2: "Outdoor Walk", 3: "Communication Practice",
                      4: "Reading / Reflection", 5: "Custom Task"}}


@mcp.tool()
def update_power_list_task(slot: int, new_name: str) -> dict:
    """Update a single Power List task name by slot (1-5)."""
    if slot < 1 or slot > 5:
        return {"error": "Slot must be 1-5"}
    conn = get_connection()
    existing = conn.execute("SELECT * FROM power_list_templates WHERE slot = ?", (slot,)).fetchone()
    if existing:
        conn.execute("UPDATE power_list_templates SET task_name = ? WHERE slot = ?", (new_name, slot))
    else:
        conn.execute("INSERT INTO power_list_templates (slot, task_name) VALUES (?, ?)", (slot, new_name))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"slot": slot, "task_name": new_name}


@mcp.tool()
def delete_power_list_day(target_date: str) -> dict:
    """Delete a Power List entry for a specific date. Use if you need to reset a day."""
    conn = get_connection()
    conn.execute("DELETE FROM power_list WHERE date = ?", (target_date,))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"date": target_date, "deleted": True}


@mcp.tool()
def get_power_list_history(days: int = 30) -> list:
    """Get Power List results for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM power_list WHERE date >= ? ORDER BY date DESC", (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# GOALS
# ============================================================

@mcp.tool()
def create_goal(
    name: str,
    category: str = "general",
    target_value: float = None,
    target_unit: str = "",
    target_date: str = "",
    notes: str = "",
) -> dict:
    """Create a new goal.

    Categories: 'weight', 'fitness', 'communication', 'discipline', 'health', 'general'
    Examples:
      - name="Lose 100 lbs", category="weight", target_value=250, target_unit="lbs", target_date="2026-09-01"
      - name="75 Hard Complete", category="discipline", target_value=75, target_unit="days"
      - name="Bench Press 225", category="fitness", target_value=225, target_unit="lbs"
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO goals (name, category, target_value, target_unit, target_date, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, category, target_value, target_unit, target_date, notes))
    conn.commit()
    row = conn.execute("SELECT id FROM goals ORDER BY id DESC LIMIT 1").fetchone()
    goal_id = row["id"] if row else 0
    sync_if_turso(conn)
    conn.close()
    return {"id": goal_id, "name": name, "category": category, "target_value": target_value,
            "target_unit": target_unit, "target_date": target_date}


@mcp.tool()
def update_goal(
    goal_id: int,
    name: str = None,
    target_value: float = None,
    target_date: str = None,
    current_value: float = None,
    status: str = None,
    notes: str = None,
) -> dict:
    """Update a goal. Only provided fields are changed.

    status options: 'active', 'completed', 'paused', 'abandoned'
    """
    conn = get_connection()
    goal = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not goal:
        conn.close()
        return {"error": f"Goal {goal_id} not found"}

    updates = []
    params = []
    if name is not None:
        updates.append("name = ?"); params.append(name)
    if target_value is not None:
        updates.append("target_value = ?"); params.append(target_value)
    if target_date is not None:
        updates.append("target_date = ?"); params.append(target_date)
    if current_value is not None:
        updates.append("current_value = ?"); params.append(current_value)
    if status is not None:
        updates.append("status = ?"); params.append(status)
    if notes is not None:
        updates.append("notes = ?"); params.append(notes)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(goal_id)
        conn.execute(f"UPDATE goals SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        sync_if_turso(conn)

    updated = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    conn.close()
    return dict(updated)


@mcp.tool()
def log_goal_progress(goal_id: int, value: float, notes: str = "", target_date: str = "") -> dict:
    """Log progress toward a goal. Also updates the goal's current_value."""
    d = target_date or date.today().isoformat()
    conn = get_connection()

    goal = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not goal:
        conn.close()
        return {"error": f"Goal {goal_id} not found"}

    conn.execute("INSERT INTO goal_progress (goal_id, date, value, notes) VALUES (?, ?, ?, ?)",
                 (goal_id, d, value, notes))
    conn.execute("UPDATE goals SET current_value = ?, updated_at = datetime('now') WHERE id = ?",
                 (value, goal_id))
    conn.commit()
    sync_if_turso(conn)

    target = goal["target_value"]
    pct = round(value / target * 100, 1) if target else 0
    conn.close()

    return {"goal": goal["name"], "current": value, "target": target,
            "progress_pct": pct, "date": d}


@mcp.tool()
def get_goals(category: str = "", status: str = "active") -> list:
    """Get all goals, optionally filtered by category and status."""
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM goals WHERE category = ? AND status = ? ORDER BY created_at",
            (category, status)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM goals WHERE status = ? ORDER BY created_at", (status,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def get_goal_progress(goal_id: int, days: int = 90) -> dict:
    """Get progress history for a specific goal."""
    conn = get_connection()
    goal = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not goal:
        conn.close()
        return {"error": f"Goal {goal_id} not found"}

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, value, notes FROM goal_progress WHERE goal_id = ? AND date >= ? ORDER BY date",
        (goal_id, cutoff)
    ).fetchall()
    conn.close()

    entries = [dict(r) for r in rows]
    return {
        "goal": dict(goal),
        "progress": entries,
        "entries_count": len(entries),
    }


@mcp.tool()
def delete_goal(goal_id: int) -> dict:
    """Delete a goal and all its progress entries."""
    conn = get_connection()
    goal = conn.execute("SELECT name FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not goal:
        conn.close()
        return {"error": f"Goal {goal_id} not found"}

    conn.execute("DELETE FROM goal_progress WHERE goal_id = ?", (goal_id,))
    conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"deleted": goal["name"]}


# ============================================================
# DAILY ROUTINE
# ============================================================

@mcp.tool()
def save_routine(
    schedule: str,
    name: str = "default",
    notes: str = "",
) -> dict:
    """Save a daily routine/schedule. The schedule should be a JSON string of time blocks:

    [
        {"time": "04:30", "activity": "Wake up"},
        {"time": "04:45", "activity": "Prayer / Gratitude"},
        {"time": "05:00", "activity": "Pre-workout + Creatine"},
        {"time": "05:15", "activity": "Gym - Strength Training", "duration": 60},
        {"time": "06:15", "activity": "Post-workout walk", "duration": 45},
        {"time": "07:00", "activity": "Shower + Get ready"},
        {"time": "08:00", "activity": "Work"},
        {"time": "12:00", "activity": "OMAD meal"},
        {"time": "13:00", "activity": "Work"},
        {"time": "17:00", "activity": "Evening walk (weighted vest)", "duration": 45},
        {"time": "18:00", "activity": "Communication practice", "duration": 30},
        {"time": "18:30", "activity": "Reading", "duration": 30},
        {"time": "19:00", "activity": "Family time"},
        {"time": "21:00", "activity": "Wind down + Sleep prep"},
        {"time": "21:30", "activity": "Sleep"}
    ]

    You can save multiple routines (e.g., 'training_day', 'rest_day', 'refeed_day').
    """
    conn = get_connection()
    # Deactivate any existing routine with same name
    conn.execute("UPDATE daily_routines SET active = 0 WHERE name = ?", (name,))
    conn.execute("""
        INSERT INTO daily_routines (name, schedule, notes)
        VALUES (?, ?, ?)
    """, (name, schedule, notes))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    try:
        blocks = json.loads(schedule)
        count = len(blocks)
    except json.JSONDecodeError:
        count = 0

    return {"name": name, "blocks": count, "saved": True}


@mcp.tool()
def get_routine(name: str = "") -> dict:
    """Get the active daily routine. If name is provided, gets that specific routine.
    Otherwise returns the default active routine.

    Use this at the start of each day to know the user's planned schedule.
    """
    conn = get_connection()
    if name:
        row = conn.execute(
            "SELECT * FROM daily_routines WHERE name = ? AND active = 1 ORDER BY created_at DESC LIMIT 1",
            (name,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM daily_routines WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    conn.close()

    if not row:
        return {"message": "No routine saved yet. Use save_routine to create one."}

    try:
        schedule = json.loads(row["schedule"])
    except json.JSONDecodeError:
        schedule = row["schedule"]

    return {"name": row["name"], "schedule": schedule, "notes": row["notes"]}


@mcp.tool()
def list_routines() -> list:
    """List all saved routines (active and inactive)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, active, notes, created_at FROM daily_routines ORDER BY active DESC, created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def delete_routine(name: str) -> dict:
    """Delete a routine by name."""
    conn = get_connection()
    conn.execute("DELETE FROM daily_routines WHERE name = ?", (name,))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"deleted": name}


# ============================================================
# DAILY EXECUTION SCORE
# ============================================================

@mcp.tool()
def score_day(
    power_list_score: float = 0,
    discipline_score: float = 0,
    nutrition_score: float = 0,
    training_score: float = 0,
    recovery_score: float = 0,
    communication_score: float = 0,
    wins: str = "",
    losses: str = "",
    lessons: str = "",
    target_date: str = "",
) -> dict:
    """Score the day's execution (0-100 for each category).

    Categories:
    - power_list_score: % of power list completed (auto-calculated if not provided)
    - discipline_score: diet adherence, water, 75 Hard compliance
    - nutrition_score: hit protein target, stayed in calorie range
    - training_score: workout quality, intensity appropriate for recovery
    - recovery_score: sleep quality, stress management, recovery protocols
    - communication_score: practiced communication skills

    wins/losses/lessons: text summaries of the day

    Total score = weighted average:
      Power List 25%, Discipline 20%, Nutrition 20%, Training 15%, Recovery 10%, Communication 10%

    Grading: A (90+), B (80-89), C (70-79), D (60-69), F (<60)
    Target: 85%+ consistently (12 Week Year standard)
    """
    d = target_date or date.today().isoformat()

    # Auto-calculate power list score if not provided
    if power_list_score == 0:
        conn = get_connection()
        pl = conn.execute("SELECT completed_count FROM power_list WHERE date = ?", (d,)).fetchone()
        if pl:
            power_list_score = pl["completed_count"] / 5 * 100
        conn.close()

    total = (
        power_list_score * 0.25 +
        discipline_score * 0.20 +
        nutrition_score * 0.20 +
        training_score * 0.15 +
        recovery_score * 0.10 +
        communication_score * 0.10
    )
    total = round(total, 1)

    if total >= 90: grade = "A"
    elif total >= 80: grade = "B"
    elif total >= 70: grade = "C"
    elif total >= 60: grade = "D"
    else: grade = "F"

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO daily_scores
        (date, power_list_score, discipline_score, nutrition_score, training_score,
         recovery_score, communication_score, total_score, grade, wins, losses, lessons)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, power_list_score, discipline_score, nutrition_score, training_score,
          recovery_score, communication_score, total, grade, wins, losses, lessons))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {
        "date": d,
        "scores": {
            "power_list": power_list_score,
            "discipline": discipline_score,
            "nutrition": nutrition_score,
            "training": training_score,
            "recovery": recovery_score,
            "communication": communication_score,
        },
        "total": total,
        "grade": grade,
        "target": "85%+",
        "on_target": total >= 85,
    }


@mcp.tool()
def get_daily_score(target_date: str = "") -> dict:
    """Get the execution score for a specific day."""
    d = target_date or date.today().isoformat()
    conn = get_connection()
    row = conn.execute("SELECT * FROM daily_scores WHERE date = ?", (d,)).fetchone()
    conn.close()
    if not row:
        return {"date": d, "message": "No score recorded for this day"}
    return dict(row)


@mcp.tool()
def get_score_history(days: int = 30) -> dict:
    """Get daily execution scores for the last N days with trend analysis."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM daily_scores WHERE date >= ? ORDER BY date", (cutoff,)
    ).fetchall()
    conn.close()

    scores = [dict(r) for r in rows]
    if scores:
        totals = [s["total_score"] for s in scores]
        avg = round(sum(totals) / len(totals), 1)
        on_target_days = sum(1 for t in totals if t >= 85)
        a_days = sum(1 for s in scores if s["grade"] == "A")
        f_days = sum(1 for s in scores if s["grade"] == "F")
    else:
        avg = 0
        on_target_days = a_days = f_days = 0

    return {
        "scores": scores,
        "average": avg,
        "on_target_pct": round(on_target_days / len(scores) * 100) if scores else 0,
        "a_days": a_days,
        "f_days": f_days,
        "days_tracked": len(scores),
        "target": "85%+",
    }


# ============================================================
# 12 WEEK YEAR
# ============================================================

@mcp.tool()
def create_12_week_year(
    name: str,
    goals: str,
    start_date: str = "",
) -> dict:
    """Start a new 12 Week Year cycle.

    goals should be a JSON string of goals with weekly actions:
    [
        {
            "goal": "Lose 30 lbs",
            "weekly_actions": ["Hit calorie target 7/7 days", "Train 6/7 days", "Walk 45 min daily"]
        },
        {
            "goal": "Build communication skills",
            "weekly_actions": ["Practice 30 min 5/7 days", "Record and review 1 speech/week"]
        }
    ]

    The 12 Week Year philosophy: execute at 85%+ of planned actions weekly.
    Week score = completed_actions / planned_actions * 100
    """
    s = start_date or date.today().isoformat()
    e = (date.fromisoformat(s) + timedelta(weeks=12)).isoformat()

    conn = get_connection()
    # Deactivate any active 12 week year
    conn.execute("UPDATE twelve_week_years SET status = 'completed' WHERE status = 'active'")
    conn.execute("""
        INSERT INTO twelve_week_years (name, start_date, end_date, goals)
        VALUES (?, ?, ?, ?)
    """, (name, s, e, goals))
    conn.commit()
    row = conn.execute("SELECT id FROM twelve_week_years ORDER BY id DESC LIMIT 1").fetchone()
    cycle_id = row["id"] if row else 0
    sync_if_turso(conn)
    conn.close()

    return {"id": cycle_id, "name": name, "start": s, "end": e, "weeks": 12}


@mcp.tool()
def log_12_week_score(
    week_number: int,
    planned_actions: int,
    completed_actions: int,
    notes: str = "",
) -> dict:
    """Log weekly score for the active 12 Week Year.

    week_number: 1-12
    planned_actions: total actions planned this week
    completed_actions: how many you actually did
    Score = completed / planned * 100. Target: 85%+
    """
    conn = get_connection()
    active = conn.execute(
        "SELECT * FROM twelve_week_years WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not active:
        conn.close()
        return {"error": "No active 12 Week Year. Create one first."}

    score = round(completed_actions / planned_actions * 100, 1) if planned_actions > 0 else 0

    conn.execute("""
        INSERT OR REPLACE INTO twelve_week_scores
        (twelve_week_id, week_number, planned_actions, completed_actions, score, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (active["id"], week_number, planned_actions, completed_actions, score, notes))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return {
        "week": week_number,
        "planned": planned_actions,
        "completed": completed_actions,
        "score": score,
        "on_target": score >= 85,
        "grade": "ON TRACK" if score >= 85 else "BELOW TARGET",
    }


@mcp.tool()
def get_12_week_progress() -> dict:
    """Get the current 12 Week Year progress — all weekly scores, trend, and projection."""
    conn = get_connection()
    active = conn.execute(
        "SELECT * FROM twelve_week_years WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not active:
        conn.close()
        return {"message": "No active 12 Week Year"}

    weeks = conn.execute(
        "SELECT * FROM twelve_week_scores WHERE twelve_week_id = ? ORDER BY week_number",
        (active["id"],)
    ).fetchall()
    conn.close()

    week_data = [dict(w) for w in weeks]
    scores = [w["score"] for w in week_data]

    if scores:
        avg = round(sum(scores) / len(scores), 1)
        on_target_weeks = sum(1 for s in scores if s >= 85)
        current_week = len(scores)
        trend = "improving" if len(scores) > 1 and scores[-1] > scores[0] else "declining" if len(scores) > 1 else "starting"
    else:
        avg = 0
        on_target_weeks = 0
        current_week = 0
        trend = "not started"

    try:
        goals = json.loads(active["goals"])
    except json.JSONDecodeError:
        goals = active["goals"]

    return {
        "name": active["name"],
        "start": active["start_date"],
        "end": active["end_date"],
        "current_week": current_week,
        "weeks_remaining": 12 - current_week,
        "goals": goals,
        "weekly_scores": week_data,
        "average_score": avg,
        "on_target_weeks": on_target_weeks,
        "trend": trend,
        "overall_grade": "ON TRACK" if avg >= 85 else "BELOW TARGET",
    }


# ============================================================
# MEAL TRACKING
# ============================================================

@mcp.tool()
def log_meal(
    description: str,
    calories: int = None,
    protein_g: float = None,
    carbs_g: float = None,
    fat_g: float = None,
    fiber_g: float = None,
    foods: str = "",
    meal_type: str = "omad",
    photo_logged: bool = False,
    notes: str = "",
    target_date: str = "",
) -> dict:
    """Log a meal. Use when user describes what they ate or sends a food photo.

    meal_type: 'omad', 'refeed', 'snack', 'pre_workout', 'post_workout'

    foods should be a JSON string of individual items if detailed tracking is needed:
    [
        {"name": "Chicken breast", "amount": "8oz", "protein": 50, "calories": 280},
        {"name": "Rice", "amount": "1 cup", "carbs": 45, "calories": 200},
        {"name": "Broccoli", "amount": "2 cups", "fiber": 5, "calories": 60}
    ]

    For OMAD user (~1500-1900 kcal target, high protein, controlled carbs 50-120g):
    - Flag if protein < 150g
    - Flag if calories > 2000
    - Flag if carbs > 120g
    """
    d = target_date or date.today().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO meals (date, meal_type, description, calories, protein_g, carbs_g,
                          fat_g, fiber_g, foods, photo_logged, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (d, meal_type, description, calories, protein_g, carbs_g,
          fat_g, fiber_g, foods, int(photo_logged), notes))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    # Warnings
    warnings = []
    if protein_g is not None and protein_g < 150:
        warnings.append(f"Protein low ({protein_g}g) — target 150g+ to preserve muscle")
    if calories is not None and calories > 2000:
        warnings.append(f"Calories high ({calories}) — OMAD target is 1500-1900")
    if carbs_g is not None and carbs_g > 120:
        warnings.append(f"Carbs high ({carbs_g}g) — target 50-120g")

    return {
        "date": d,
        "meal_type": meal_type,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "warnings": warnings,
    }


@mcp.tool()
def get_meals(target_date: str = "") -> list:
    """Get all meals logged for a date."""
    d = target_date or date.today().isoformat()
    conn = get_connection()
    rows = conn.execute("SELECT * FROM meals WHERE date = ? ORDER BY created_at", (d,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def get_meal_history(days: int = 30) -> dict:
    """Get meal history with daily macro totals for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date,
               SUM(calories) as total_calories,
               SUM(protein_g) as total_protein,
               SUM(carbs_g) as total_carbs,
               SUM(fat_g) as total_fat,
               SUM(fiber_g) as total_fiber,
               COUNT(*) as meal_count
        FROM meals
        WHERE date >= ?
        GROUP BY date
        ORDER BY date DESC
    """, (cutoff,)).fetchall()
    conn.close()

    daily = [dict(r) for r in rows]

    # Averages
    if daily:
        avg_cal = round(sum(d["total_calories"] or 0 for d in daily) / len(daily))
        avg_pro = round(sum(d["total_protein"] or 0 for d in daily) / len(daily))
        avg_carb = round(sum(d["total_carbs"] or 0 for d in daily) / len(daily))
    else:
        avg_cal = avg_pro = avg_carb = 0

    return {
        "daily_totals": daily,
        "averages": {"calories": avg_cal, "protein_g": avg_pro, "carbs_g": avg_carb},
        "days_tracked": len(daily),
    }


@mcp.tool()
def delete_meal(meal_id: int) -> dict:
    """Delete a meal entry by ID."""
    conn = get_connection()
    meal = conn.execute("SELECT date, description FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if not meal:
        conn.close()
        return {"error": f"Meal {meal_id} not found"}
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return {"deleted": meal["description"], "date": meal["date"]}


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    port = int(os.getenv("PORT", "8000"))

    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
    else:
        mcp.run()

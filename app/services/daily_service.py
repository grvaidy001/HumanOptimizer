"""Service layer for daily logs and power list operations."""

from datetime import date, timedelta
from app.db import get_connection, sync_if_turso
from app.models import DailyLog, PowerList, SevenFiveHard


def save_daily_log(log: DailyLog) -> DailyLog:
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO daily_logs
        (date, weight, fasting_day, fasting_cycle_day, day_type, recovery, strain,
         sleep_score, rhr, hrv, walk_minutes, vest_weight, communication_minutes,
         communication_sessions, communication_notes, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log.date, log.weight, int(log.fasting_day), log.fasting_cycle_day,
        log.day_type, log.recovery, log.strain, log.sleep_score, log.rhr,
        log.hrv, log.walk_minutes, log.vest_weight, log.communication_minutes,
        log.communication_sessions, log.communication_notes, log.notes,
    ))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return log


def get_daily_log(target_date: str) -> DailyLog | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if row:
        return DailyLog(**dict(row))
    return None


def save_power_list(pl: PowerList) -> PowerList:
    # Calculate completed count and result
    tasks = [pl.task1_done, pl.task2_done, pl.task3_done, pl.task4_done, pl.task5_done]
    pl.completed_count = sum(tasks)
    pl.result = "WIN" if pl.completed_count == 5 else "LOSS" if any(tasks) or pl.completed_count > 0 else "PENDING"
    # If at least one task attempted but not all done, it's a loss
    # If nothing attempted, it's pending
    if pl.completed_count == 5:
        pl.result = "WIN"
    elif pl.completed_count > 0:
        pl.result = "LOSS"
    else:
        pl.result = "PENDING"

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO power_list
        (date, task1_name, task1_done, task2_name, task2_done, task3_name, task3_done,
         task4_name, task4_done, task5_name, task5_done, completed_count, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pl.date, pl.task1_name, int(pl.task1_done), pl.task2_name, int(pl.task2_done),
        pl.task3_name, int(pl.task3_done), pl.task4_name, int(pl.task4_done),
        pl.task5_name, int(pl.task5_done), pl.completed_count, pl.result,
    ))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return pl


def get_power_list(target_date: str) -> PowerList | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM power_list WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if row:
        return PowerList(**dict(row))
    return None


def save_75_hard(data: SevenFiveHard) -> SevenFiveHard:
    tasks = [data.workout1, data.workout2_outdoor, data.reading_10_pages,
             data.water_gallon, data.diet_followed, data.progress_photo]
    data.all_complete = all(tasks)

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO seven_five_hard
        (date, workout1, workout2_outdoor, reading_10_pages, water_gallon,
         diet_followed, progress_photo, all_complete)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.date, int(data.workout1), int(data.workout2_outdoor),
        int(data.reading_10_pages), int(data.water_gallon),
        int(data.diet_followed), int(data.progress_photo), int(data.all_complete),
    ))
    conn.commit()
    sync_if_turso(conn)
    conn.close()
    return data


def get_75_hard(target_date: str) -> SevenFiveHard | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM seven_five_hard WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if row:
        return SevenFiveHard(**dict(row))
    return None


def get_streak() -> int:
    """Calculate current WIN streak."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, result FROM power_list ORDER BY date DESC"
    ).fetchall()
    conn.close()

    streak = 0
    for row in rows:
        if row["result"] == "WIN":
            streak += 1
        else:
            break
    return streak


def get_win_rate(days: int = 30) -> dict:
    """Get win/loss stats for the last N days."""
    conn = get_connection()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT result, COUNT(*) as cnt FROM power_list WHERE date >= ? GROUP BY result",
        (cutoff,)
    ).fetchall()
    conn.close()

    stats = {"wins": 0, "losses": 0, "pending": 0, "total": 0, "win_rate": 0}
    for row in rows:
        if row["result"] == "WIN":
            stats["wins"] = row["cnt"]
        elif row["result"] == "LOSS":
            stats["losses"] = row["cnt"]
        else:
            stats["pending"] = row["cnt"]
    stats["total"] = stats["wins"] + stats["losses"]
    if stats["total"] > 0:
        stats["win_rate"] = round(stats["wins"] / stats["total"] * 100, 1)
    return stats

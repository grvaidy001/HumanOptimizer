"""Weekly summary generation service."""

from datetime import date, timedelta
from app.db import get_connection, sync_if_turso
from app.models import WeeklySummary


def get_week_start(target_date: date = None) -> date:
    """Get Monday of the current week."""
    d = target_date or date.today()
    return d - timedelta(days=d.weekday())


def generate_weekly_summary(week_start_date: date = None) -> WeeklySummary:
    """Generate a weekly summary for the week starting on the given Monday."""
    ws = get_week_start(week_start_date)
    we = ws + timedelta(days=6)

    conn = get_connection()

    # Power list stats
    pl_rows = conn.execute(
        "SELECT result FROM power_list WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()

    wins = sum(1 for r in pl_rows if r["result"] == "WIN")
    losses = sum(1 for r in pl_rows if r["result"] == "LOSS")
    total = wins + losses
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    # Weight change
    weight_rows = conn.execute(
        "SELECT date, weight FROM daily_logs WHERE date BETWEEN ? AND ? AND weight IS NOT NULL ORDER BY date",
        (ws.isoformat(), we.isoformat())
    ).fetchall()

    weight_start = weight_rows[0]["weight"] if weight_rows else None
    weight_end = weight_rows[-1]["weight"] if weight_rows else None
    weight_change = round(weight_end - weight_start, 1) if weight_start and weight_end else None

    # Streak
    all_pl = conn.execute(
        "SELECT result FROM power_list ORDER BY date DESC"
    ).fetchall()
    streak = 0
    for r in all_pl:
        if r["result"] == "WIN":
            streak += 1
        else:
            break

    # Consistency metrics
    log_rows = conn.execute(
        "SELECT * FROM daily_logs WHERE date BETWEEN ? AND ?",
        (ws.isoformat(), we.isoformat())
    ).fetchall()

    days_logged = len(log_rows)
    if days_logged > 0:
        gym_days = sum(1 for r in pl_rows if r["result"] in ("WIN", "LOSS"))  # approximation
        walk_days = sum(1 for r in log_rows if r["walk_minutes"] and r["walk_minutes"] > 0)
        comm_days = sum(1 for r in log_rows if r["communication_minutes"] and r["communication_minutes"] > 0)
        gym_consistency = round(gym_days / 7 * 100, 1)
        walk_consistency = round(walk_days / 7 * 100, 1)
        communication_consistency = round(comm_days / 7 * 100, 1)
    else:
        gym_consistency = walk_consistency = communication_consistency = 0

    conn.close()

    # Generate summary text
    summary_parts = []
    if win_rate >= 80:
        summary_parts.append("DOMINANT WEEK. Keep this energy.")
    elif win_rate >= 60:
        summary_parts.append("Solid week. Room to tighten up.")
    elif win_rate > 0:
        summary_parts.append("Inconsistent week. Identify what's slipping.")
    else:
        summary_parts.append("No data yet for this week.")

    if weight_change is not None:
        if weight_change < 0:
            summary_parts.append(f"Weight down {abs(weight_change)} lbs — progress.")
        elif weight_change > 0:
            summary_parts.append(f"Weight up {weight_change} lbs — check diet adherence.")
        else:
            summary_parts.append("Weight stable.")

    if walk_consistency < 70:
        summary_parts.append("Walking consistency needs work — aim for daily walks.")
    if communication_consistency < 50:
        summary_parts.append("Communication practice slipping — schedule it.")

    summary_text = " ".join(summary_parts)

    result = WeeklySummary(
        week_start=ws.isoformat(),
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        weight_start=weight_start,
        weight_end=weight_end,
        weight_change=weight_change,
        streak=streak,
        gym_consistency=gym_consistency,
        walk_consistency=walk_consistency,
        communication_consistency=communication_consistency,
        summary=summary_text,
    )

    # Save to db
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO weekly_summaries
        (week_start, wins, losses, win_rate, weight_start, weight_end, weight_change,
         streak, gym_consistency, walk_consistency, communication_consistency, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result.week_start, result.wins, result.losses, result.win_rate,
        result.weight_start, result.weight_end, result.weight_change,
        result.streak, result.gym_consistency, result.walk_consistency,
        result.communication_consistency, result.summary,
    ))
    conn.commit()
    sync_if_turso(conn)
    conn.close()

    return result

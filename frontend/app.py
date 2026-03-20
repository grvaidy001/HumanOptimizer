"""Streamlit frontend for HumanOptimizer — Personal Execution OS."""

import streamlit as st
import requests
from datetime import date, timedelta

API = "http://localhost:8000/api"

st.set_page_config(
    page_title="HumanOptimizer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Styling ---
st.markdown("""
<style>
    .win-badge { background: #22c55e; color: white; padding: 8px 24px; border-radius: 8px;
                 font-size: 28px; font-weight: bold; text-align: center; margin: 8px 0; }
    .loss-badge { background: #ef4444; color: white; padding: 8px 24px; border-radius: 8px;
                  font-size: 28px; font-weight: bold; text-align: center; margin: 8px 0; }
    .pending-badge { background: #f59e0b; color: white; padding: 8px 24px; border-radius: 8px;
                     font-size: 28px; font-weight: bold; text-align: center; margin: 8px 0; }
    .status-green { background: #22c55e; color: white; padding: 4px 12px; border-radius: 4px; font-weight: bold; }
    .status-yellow { background: #f59e0b; color: white; padding: 4px 12px; border-radius: 4px; font-weight: bold; }
    .status-red { background: #ef4444; color: white; padding: 4px 12px; border-radius: 4px; font-weight: bold; }
    .metric-card { background: #1e293b; padding: 16px; border-radius: 8px; text-align: center; margin: 4px 0; }
    .streak-display { font-size: 48px; font-weight: bold; text-align: center; }
</style>
""", unsafe_allow_html=True)


def api_get(endpoint: str, default=None):
    try:
        r = requests.get(f"{API}{endpoint}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except requests.ConnectionError:
        st.error("Cannot connect to backend. Run: `uvicorn app.main:app --reload`")
    return default


def api_post(endpoint: str, data: dict):
    try:
        r = requests.post(f"{API}{endpoint}", json=data, timeout=5)
        return r.json()
    except requests.ConnectionError:
        st.error("Cannot connect to backend.")
    return None


def api_delete(endpoint: str):
    try:
        r = requests.delete(f"{API}{endpoint}", timeout=5)
        return r.json()
    except requests.ConnectionError:
        st.error("Cannot connect to backend.")
    return None


# --- Sidebar ---
st.sidebar.title("HumanOptimizer")
st.sidebar.markdown("**Personal Execution OS**")
page = st.sidebar.radio("Navigate", ["Today", "Fitness", "Weekly Review", "Communication", "75 Hard", "Integrations"])
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Date:** {date.today().isoformat()}")

# Streak display in sidebar
streak_data = api_get("/stats/streak", {"streak": 0})
streak = streak_data.get("streak", 0) if streak_data else 0
st.sidebar.markdown(f"**Current Streak:** {streak} day{'s' if streak != 1 else ''}")

stats = api_get("/stats/win-rate", {})
if stats:
    st.sidebar.markdown(f"**Win Rate (30d):** {stats.get('win_rate', 0)}%")
    st.sidebar.markdown(f"**Wins:** {stats.get('wins', 0)} | **Losses:** {stats.get('losses', 0)}")


# =============================================================================
# TODAY PAGE
# =============================================================================
if page == "Today":
    st.title("TODAY — Execute or Fail")
    today = date.today().isoformat()

    col_main, col_side = st.columns([2, 1])

    with col_main:
        # --- POWER LIST ---
        st.header("Power List")
        st.markdown("*Complete all 5 to WIN the day.*")

        existing_pl = api_get(f"/power-list/{today}")
        defaults = existing_pl or {}

        task1_name = st.text_input("Task 1", value=defaults.get("task1_name", "Gym Workout"), key="t1n")
        task1_done = st.checkbox("Done", value=defaults.get("task1_done", False), key="t1d")

        task2_name = st.text_input("Task 2", value=defaults.get("task2_name", "Outdoor Walk"), key="t2n")
        task2_done = st.checkbox("Done", value=defaults.get("task2_done", False), key="t2d")

        task3_name = st.text_input("Task 3", value=defaults.get("task3_name", "Communication Practice"), key="t3n")
        task3_done = st.checkbox("Done", value=defaults.get("task3_done", False), key="t3d")

        task4_name = st.text_input("Task 4", value=defaults.get("task4_name", "Reading / Reflection"), key="t4n")
        task4_done = st.checkbox("Done", value=defaults.get("task4_done", False), key="t4d")

        task5_name = st.text_input("Task 5", value=defaults.get("task5_name", "Custom Task"), key="t5n")
        task5_done = st.checkbox("Done", value=defaults.get("task5_done", False), key="t5d")

        if st.button("Save Power List", type="primary", use_container_width=True):
            pl_data = {
                "date": today,
                "task1_name": task1_name, "task1_done": task1_done,
                "task2_name": task2_name, "task2_done": task2_done,
                "task3_name": task3_name, "task3_done": task3_done,
                "task4_name": task4_name, "task4_done": task4_done,
                "task5_name": task5_name, "task5_done": task5_done,
            }
            result = api_post("/power-list", pl_data)
            if result:
                st.rerun()

        # Show result
        completed = sum([task1_done, task2_done, task3_done, task4_done, task5_done])
        st.markdown(f"### {completed}/5 Complete")
        if completed == 5:
            st.markdown('<div class="win-badge">WIN</div>', unsafe_allow_html=True)
        elif completed > 0:
            st.markdown('<div class="loss-badge">NOT YET — FINISH IT</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pending-badge">PENDING — GET TO WORK</div>', unsafe_allow_html=True)

    with col_side:
        # --- DAILY LOG ---
        st.header("Daily Log")

        # Quick-pull from integrations
        int_status = api_get("/integrations/status", {})
        whoop_connected = int_status.get("whoop", {}).get("connected") if int_status else False
        if whoop_connected:
            if st.button("Pull from WHOOP", key="whoop_pull"):
                metrics = api_get(f"/integrations/whoop/metrics/{today}")
                if metrics:
                    log_data = {k: v for k, v in {
                        "date": today,
                        "recovery": metrics.get("recovery"),
                        "strain": metrics.get("strain"),
                        "sleep_score": metrics.get("sleep_score"),
                        "rhr": metrics.get("rhr"),
                        "hrv": metrics.get("hrv"),
                        "weight": metrics.get("weight"),
                    }.items() if v is not None}
                    if len(log_data) > 1:
                        api_post("/daily-log", log_data)
                        st.success("WHOOP data imported!")
                        st.rerun()

        existing_log = api_get(f"/daily-log/{today}")
        log_defaults = existing_log or {}

        DAY_TYPES = ["Upper", "Lower + Sled", "Recovery", "Refeed/Heavy"]
        weight = st.number_input("Weight (lbs)", value=float(log_defaults.get("weight") or 0),
                                 min_value=0.0, max_value=600.0, step=0.1)
        fasting_day = st.checkbox("Fasting Day", value=log_defaults.get("fasting_day", False))
        fasting_cycle_day = st.selectbox("Fasting Cycle Day", [1, 2, 3, 4],
                                         index=(log_defaults.get("fasting_cycle_day", 1) - 1))
        day_type = st.selectbox("Day Type", DAY_TYPES,
                                index=DAY_TYPES.index(log_defaults.get("day_type", "Upper")))

        st.subheader("Recovery")
        recovery = st.slider("Recovery %", 0, 100, log_defaults.get("recovery") or 70)
        strain = st.slider("Strain", 0, 21, log_defaults.get("strain") or 10)
        sleep_score = st.slider("Sleep Score", 0, 100, log_defaults.get("sleep_score") or 70)
        rhr = st.number_input("Resting HR", value=int(log_defaults.get("rhr") or 65), min_value=30, max_value=120)
        hrv = st.number_input("HRV", value=int(log_defaults.get("hrv") or 40), min_value=0, max_value=200)

        st.subheader("Activity")
        walk_minutes = st.number_input("Walk Minutes", value=int(log_defaults.get("walk_minutes") or 0),
                                        min_value=0, max_value=300)
        vest_weight = st.number_input("Vest Weight (lbs)", value=float(log_defaults.get("vest_weight") or 0),
                                       min_value=0.0, max_value=100.0, step=0.5)

        st.subheader("Communication")
        comm_minutes = st.number_input("Minutes Practiced", value=int(log_defaults.get("communication_minutes") or 0),
                                        min_value=0, max_value=180)
        comm_sessions = st.number_input("Sessions", value=int(log_defaults.get("communication_sessions") or 0),
                                         min_value=0, max_value=20)
        comm_notes = st.text_area("Communication Notes", value=log_defaults.get("communication_notes", ""))

        notes = st.text_area("Daily Notes", value=log_defaults.get("notes", ""))

        if st.button("Save Daily Log", use_container_width=True):
            log_data = {
                "date": today, "weight": weight if weight > 0 else None,
                "fasting_day": fasting_day, "fasting_cycle_day": fasting_cycle_day,
                "day_type": day_type, "recovery": recovery, "strain": strain,
                "sleep_score": sleep_score, "rhr": rhr, "hrv": hrv,
                "walk_minutes": walk_minutes, "vest_weight": vest_weight,
                "communication_minutes": comm_minutes, "communication_sessions": comm_sessions,
                "communication_notes": comm_notes, "notes": notes,
            }
            api_post("/daily-log", log_data)
            st.success("Daily log saved!")

        # --- COACHING ---
        st.header("Coaching Plan")
        if st.button("Get Today's Plan", use_container_width=True):
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            prev_pl = api_get(f"/power-list/{yesterday}")
            prev_result = prev_pl.get("result", "PENDING") if prev_pl else "PENDING"

            coaching_input = {
                "recovery": recovery, "strain": strain, "fasting_day": fasting_day,
                "fasting_cycle_day": fasting_cycle_day, "day_type": day_type,
                "previous_result": prev_result, "sleep_score": sleep_score, "hrv": hrv,
            }
            plan = api_post("/coaching/plan", coaching_input)
            if plan:
                status_class = f"status-{plan['status'].lower()}"
                st.markdown(f'<span class="{status_class}">{plan["status"]}</span>', unsafe_allow_html=True)
                st.markdown(f"**Training:** {plan['training']}")
                st.markdown(f"**Sled:** {plan['sled']}")
                st.markdown(f"**Walk:** {plan['walk']}")
                st.markdown(f"**Communication Task:** {plan['communication_task']}")
                if plan.get("warning"):
                    st.warning(plan["warning"])


# =============================================================================
# FITNESS PAGE
# =============================================================================
elif page == "Fitness":
    st.title("Fitness & Body Transformation")

    # Weight trend
    st.header("Weight Trend")
    from app.db import get_connection
    conn = get_connection()
    weight_data = conn.execute(
        "SELECT date, weight FROM daily_logs WHERE weight IS NOT NULL ORDER BY date DESC LIMIT 30"
    ).fetchall()
    conn.close()

    if weight_data:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in weight_data])
        df = df.sort_values("date")
        st.line_chart(df.set_index("date")["weight"])

        col1, col2, col3 = st.columns(3)
        latest = df.iloc[-1]["weight"]
        earliest = df.iloc[0]["weight"]
        change = round(latest - earliest, 1)
        col1.metric("Current Weight", f"{latest} lbs")
        col2.metric("Start Weight", f"{earliest} lbs")
        col3.metric("Change", f"{change} lbs", delta=f"{change} lbs",
                     delta_color="inverse")
    else:
        st.info("No weight data yet. Log your weight on the Today page.")

    # Recent logs
    st.header("Recent Logs")
    conn = get_connection()
    logs = conn.execute(
        "SELECT date, weight, day_type, fasting_cycle_day, recovery, walk_minutes FROM daily_logs ORDER BY date DESC LIMIT 14"
    ).fetchall()
    conn.close()

    if logs:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in logs])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No logs yet.")


# =============================================================================
# WEEKLY REVIEW PAGE
# =============================================================================
elif page == "Weekly Review":
    st.title("Weekly Review")

    summary = api_get("/weekly-summary")
    if summary:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Wins", summary.get("wins", 0))
        col2.metric("Losses", summary.get("losses", 0))
        col3.metric("Win Rate", f"{summary.get('win_rate', 0)}%")
        col4.metric("Streak", summary.get("streak", 0))

        if summary.get("weight_change") is not None:
            st.metric("Weight Change", f"{summary['weight_change']} lbs",
                       delta=f"{summary['weight_change']} lbs", delta_color="inverse")

        st.subheader("Consistency")
        col1, col2, col3 = st.columns(3)
        col1.metric("Gym", f"{summary.get('gym_consistency', 0)}%")
        col2.metric("Walking", f"{summary.get('walk_consistency', 0)}%")
        col3.metric("Communication", f"{summary.get('communication_consistency', 0)}%")

        st.subheader("Summary")
        st.info(summary.get("summary", "No summary yet."))
    else:
        st.info("No weekly data yet. Start logging daily to generate summaries.")

    # Historical weeks
    st.header("Past Weeks")
    from app.db import get_connection
    conn = get_connection()
    weeks = conn.execute(
        "SELECT * FROM weekly_summaries ORDER BY week_start DESC LIMIT 8"
    ).fetchall()
    conn.close()
    if weeks:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in weeks])
        st.dataframe(df[["week_start", "wins", "losses", "win_rate", "weight_change", "streak"]],
                      use_container_width=True)


# =============================================================================
# COMMUNICATION PAGE
# =============================================================================
elif page == "Communication":
    st.title("Communication Development")

    st.header("Practice Suggestions")
    suggestions = [
        "Explain a complex concept in under 3 minutes",
        "Record and review a speech",
        "Practice your elevator pitch",
        "Summarize an article verbally",
        "Describe your goals to an imaginary audience",
        "Practice giving feedback on a piece of work",
    ]
    for s in suggestions:
        st.markdown(f"- {s}")

    st.header("Recent Communication Logs")
    from app.db import get_connection
    conn = get_connection()
    comm_data = conn.execute(
        "SELECT date, communication_minutes, communication_sessions, communication_notes "
        "FROM daily_logs WHERE communication_minutes > 0 ORDER BY date DESC LIMIT 14"
    ).fetchall()
    conn.close()

    if comm_data:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in comm_data])
        st.dataframe(df, use_container_width=True)

        total_mins = df["communication_minutes"].sum()
        total_sessions = df["communication_sessions"].sum()
        col1, col2 = st.columns(2)
        col1.metric("Total Minutes (recent)", int(total_mins))
        col2.metric("Total Sessions (recent)", int(total_sessions))
    else:
        st.info("No communication practice logged yet. Log on the Today page.")


# =============================================================================
# 75 HARD PAGE
# =============================================================================
elif page == "75 Hard":
    st.title("75 Hard Tracker")
    today = date.today().isoformat()

    existing = api_get(f"/75-hard/{today}")
    defaults = existing or {}

    st.markdown("*Complete ALL 6 tasks every day. No excuses. No substitutions.*")

    workout1 = st.checkbox("Workout #1 (45 min)", value=defaults.get("workout1", False))
    workout2 = st.checkbox("Workout #2 — Outdoor (45 min)", value=defaults.get("workout2_outdoor", False))
    reading = st.checkbox("Read 10 Pages (non-fiction)", value=defaults.get("reading_10_pages", False))
    water = st.checkbox("Drink 1 Gallon Water", value=defaults.get("water_gallon", False))
    diet = st.checkbox("Follow Diet (no cheats, no alcohol)", value=defaults.get("diet_followed", False))
    photo = st.checkbox("Progress Photo", value=defaults.get("progress_photo", False))

    tasks = [workout1, workout2, reading, water, diet, photo]
    completed = sum(tasks)
    st.markdown(f"### {completed}/6 Complete")

    if all(tasks):
        st.markdown('<div class="win-badge">75 HARD — DAY COMPLETE</div>', unsafe_allow_html=True)
    elif completed > 0:
        st.markdown(f'<div class="loss-badge">INCOMPLETE — {6 - completed} remaining</div>', unsafe_allow_html=True)

    if st.button("Save 75 Hard", type="primary", use_container_width=True):
        data = {
            "date": today,
            "workout1": workout1,
            "workout2_outdoor": workout2,
            "reading_10_pages": reading,
            "water_gallon": water,
            "diet_followed": diet,
            "progress_photo": photo,
        }
        api_post("/75-hard", data)
        st.rerun()

    # 75 Hard streak
    st.header("75 Hard Progress")
    from app.db import get_connection
    conn = get_connection()
    hard_data = conn.execute(
        "SELECT date, all_complete FROM seven_five_hard ORDER BY date DESC LIMIT 75"
    ).fetchall()
    conn.close()

    if hard_data:
        hard_streak = 0
        for row in hard_data:
            if row["all_complete"]:
                hard_streak += 1
            else:
                break
        st.metric("75 Hard Streak", f"{hard_streak} days")
        st.progress(min(hard_streak / 75, 1.0), text=f"Day {hard_streak} / 75")
    else:
        st.info("Start tracking 75 Hard to see your progress.")


# =============================================================================
# INTEGRATIONS PAGE
# =============================================================================
elif page == "Integrations":
    st.title("Integrations")
    st.markdown("Connect external fitness services to auto-populate your daily metrics.")

    # Status
    status = api_get("/integrations/status", {})

    # --- WHOOP ---
    st.header("WHOOP")
    whoop_status = status.get("whoop", {}) if status else {}

    if whoop_status.get("connected"):
        st.success("Connected")
        today = date.today().isoformat()

        if st.button("Pull Today's WHOOP Data"):
            metrics = api_get(f"/integrations/whoop/metrics/{today}")
            if metrics:
                st.json(metrics)
                # Auto-fill daily log
                log_data = {
                    "date": today,
                    "recovery": metrics.get("recovery"),
                    "strain": metrics.get("strain"),
                    "sleep_score": metrics.get("sleep_score"),
                    "rhr": metrics.get("rhr"),
                    "hrv": metrics.get("hrv"),
                    "weight": metrics.get("weight"),
                }
                # Filter out None values
                log_data = {k: v for k, v in log_data.items() if v is not None}
                if len(log_data) > 1:  # more than just date
                    api_post("/daily-log", log_data)
                    st.success("WHOOP data saved to daily log!")

        if st.button("Disconnect WHOOP"):
            api_delete("/integrations/whoop")
            st.rerun()
    else:
        st.warning("Not connected")
        with st.expander("Setup WHOOP Connection"):
            st.markdown("""
            1. Register an app at [developer.whoop.com](https://developer.whoop.com)
            2. Set redirect URI to: `http://localhost:8000/api/integrations/whoop/callback`
            3. Enter your credentials below
            """)
            whoop_client_id = st.text_input("WHOOP Client ID")
            whoop_client_secret = st.text_input("WHOOP Client Secret", type="password")

            if st.button("Save WHOOP Credentials"):
                if whoop_client_id and whoop_client_secret:
                    api_post(f"/integrations/whoop/configure?client_id={whoop_client_id}&client_secret={whoop_client_secret}", {})
                    st.success("Credentials saved!")
                    st.rerun()
                else:
                    st.error("Both fields required")

            if whoop_status.get("configured"):
                auth_data = api_get("/integrations/whoop/auth-url")
                if auth_data:
                    st.markdown(f"[Click here to connect WHOOP]({auth_data['url']})")

    st.markdown("---")

    # --- HEVY ---
    st.header("Hevy")
    hevy_status = status.get("hevy", {}) if status else {}

    if hevy_status.get("connected"):
        st.success("Connected")

        # Show workout count
        count_data = api_get("/integrations/hevy/count")
        if count_data:
            st.metric("Total Workouts in Hevy", count_data.get("workout_count", 0))

        # Show today's workouts
        today = date.today().isoformat()
        if st.button("Pull Today's Hevy Workouts"):
            workouts = api_get(f"/integrations/hevy/workouts/{today}", [])
            if workouts:
                for w in workouts:
                    st.subheader(w["title"])
                    st.markdown(f"**Duration:** {w['duration_minutes']} min | **Volume:** {w['total_volume_lbs']} lbs")
                    for ex in w.get("exercises", []):
                        top = ex.get("top_set")
                        top_str = f" — Top: {top['weight_lbs']} lbs x {top['reps']}" if top else ""
                        st.markdown(f"- {ex['title']}{top_str}")
            else:
                st.info("No workouts found for today.")

        # Recent workouts
        if st.button("Show Recent Workouts"):
            workouts = api_get("/integrations/hevy/workouts?page=1", [])
            if workouts:
                for w in workouts:
                    st.markdown(f"**{w['title']}** — {w['start_time'][:10]} — {w['duration_minutes']} min — {w['total_volume_lbs']} lbs")

        if st.button("Disconnect Hevy"):
            api_delete("/integrations/hevy")
            st.rerun()
    else:
        st.warning("Not connected")
        with st.expander("Setup Hevy Connection"):
            st.markdown("""
            1. Subscribe to [Hevy Pro](https://hevy.com)
            2. Go to [Settings > Developer](https://hevy.com/settings?developer)
            3. Generate an API key
            4. Enter it below
            """)
            hevy_api_key = st.text_input("Hevy API Key", type="password")

            if st.button("Save Hevy API Key"):
                if hevy_api_key:
                    api_post(f"/integrations/hevy/configure?api_key={hevy_api_key}", {})
                    st.success("API key saved!")
                    st.rerun()
                else:
                    st.error("API key required")

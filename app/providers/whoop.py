"""WHOOP API integration for MCP server.

OAuth2 flow:
1. Call whoop_start_auth → get URL → user opens in browser
2. WHOOP redirects with code → call whoop_complete_auth with the code
3. Tokens stored in DB, auto-refreshed on every API call
"""

import os
import urllib.parse
from datetime import datetime, timedelta, date, timezone

import requests

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v1"

SCOPES = "read:recovery read:sleep read:workout read:cycles read:body_measurement read:profile offline"

CLIENT_ID = os.getenv("WHOOP_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8000/whoop/callback")


def get_auth_url(state: str = "whoop_auth") -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _refresh_tokens(refresh_token: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "offline",
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


def save_tokens(conn, token_data: dict):
    expires = datetime.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 3600))
    conn.execute("""
        INSERT OR REPLACE INTO whoop_tokens (id, access_token, refresh_token, expires_at, scopes)
        VALUES (1, ?, ?, ?, ?)
    """, (token_data["access_token"], token_data["refresh_token"],
          expires.isoformat(), token_data.get("scope", SCOPES)))
    conn.commit()


def _bootstrap_from_env(conn):
    """If DB has no tokens but env vars do, seed from env (survives redeploys)."""
    row = conn.execute("SELECT * FROM whoop_tokens WHERE id = 1").fetchone()
    if row:
        return
    refresh = os.getenv("WHOOP_REFRESH_TOKEN", "")
    if not refresh:
        return
    try:
        data = _refresh_tokens(refresh)
        save_tokens(conn, data)
    except Exception:
        pass


def _get_valid_token(conn) -> str:
    _bootstrap_from_env(conn)
    row = conn.execute("SELECT * FROM whoop_tokens WHERE id = 1").fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) < expires_at - timedelta(minutes=1):
        return row["access_token"]
    try:
        data = _refresh_tokens(row["refresh_token"])
        save_tokens(conn, data)
        return data["access_token"]
    except Exception:
        return None


def is_connected(conn) -> bool:
    return _get_valid_token(conn) is not None


def _api_get(token: str, path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=15,
    )
    if resp.status_code == 404:
        return {"records": []}
    if resp.status_code == 401:
        return {"error": "Token expired or invalid", "status": 401}
    resp.raise_for_status()
    return resp.json()


def _paginate_all(token: str, path: str, start: str, end: str, max_pages: int = 4) -> list:
    all_records = []
    params = {"start": start, "end": end, "limit": 25}
    pages = 0
    while pages < max_pages:
        data = _api_get(token, path, params)
        if "error" in data:
            break
        records = data.get("records", [])
        all_records.extend(records)
        next_token = data.get("next_token")
        if not next_token or not records:
            break
        params["nextToken"] = next_token
        pages += 1
    return all_records


def _extract_date_from_record(record: dict) -> str:
    for field in ["start", "created_at"]:
        if field in record and record[field]:
            return record[field][:10]
    return date.today().isoformat()


def _extract_recovery(rec: dict) -> dict:
    """Extract all recovery fields from a WHOOP recovery record."""
    score = rec.get("score") or {}
    return {
        "recovery_score": score.get("recovery_score"),
        "hrv": score.get("hrv_rmssd_milli"),
        "rhr": score.get("resting_heart_rate"),
        "spo2": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
        "score_state": rec.get("score_state"),
        "user_calibrating": score.get("user_calibrating"),
    }


def _extract_sleep(rec: dict) -> dict:
    """Extract all sleep fields from a WHOOP sleep record."""
    score = rec.get("score") or {}
    stages = score.get("stage_summary") or {}

    total_in_bed = stages.get("total_in_bed_time_milli", 0) or 0
    total_awake = stages.get("total_awake_time_milli", 0) or 0
    total_sleep_ms = total_in_bed - total_awake
    total_rem = stages.get("total_rem_sleep_time_milli", 0) or 0
    total_sws = stages.get("total_slow_wave_sleep_time_milli", 0) or 0
    total_light = stages.get("total_light_sleep_time_milli", 0) or 0

    sleep_needed = score.get("sleep_needed") or {}

    return {
        "sleep_hours": round(total_sleep_ms / 3600000, 1) if total_sleep_ms else None,
        "sleep_performance": score.get("sleep_performance_percentage"),
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "sleep_consistency": score.get("sleep_consistency_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "rem_hours": round(total_rem / 3600000, 1) if total_rem else None,
        "deep_sleep_hours": round(total_sws / 3600000, 1) if total_sws else None,
        "light_sleep_hours": round(total_light / 3600000, 1) if total_light else None,
        "time_in_bed_hours": round(total_in_bed / 3600000, 1) if total_in_bed else None,
        "disturbances": stages.get("disturbance_count"),
        "sleep_cycles": stages.get("sleep_cycle_count"),
        "sleep_needed_hours": round((sleep_needed.get("baseline_milli", 0) or 0) / 3600000, 1),
        "sleep_debt_hours": round((sleep_needed.get("need_from_sleep_debt_milli", 0) or 0) / 3600000, 1),
        "is_nap": rec.get("nap", False),
        "score_state": rec.get("score_state"),
    }


def _extract_strain(rec: dict) -> dict:
    """Extract all strain/cycle fields from a WHOOP cycle record."""
    score = rec.get("score") or {}
    return {
        "strain": score.get("strain"),
        "kilojoule": score.get("kilojoule"),
        "calories_burned": round(score["kilojoule"] * 0.239006) if score.get("kilojoule") else None,
        "avg_hr": score.get("average_heart_rate"),
        "max_hr": score.get("max_heart_rate"),
        "score_state": rec.get("score_state"),
    }


def fetch_recovery(conn, target_date: str = None) -> dict:
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    start = f"{d}T00:00:00.000Z"
    end = f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    records = _paginate_all(token, "/recovery", start, end)
    if not records:
        data = _api_get(token, "/recovery", {"limit": 10})
        records = data.get("records", [])
        records = [r for r in records if _extract_date_from_record(r) == d]

    if not records:
        return {"date": d, "data": None, "message": "No recovery data"}

    result = _extract_recovery(records[0])
    result["date"] = d
    return result


def fetch_sleep(conn, target_date: str = None) -> dict:
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    start = f"{d}T00:00:00.000Z"
    end = f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    records = _paginate_all(token, "/activity/sleep", start, end)
    if not records:
        data = _api_get(token, "/activity/sleep", {"limit": 10})
        records = data.get("records", [])
        records = [r for r in records if _extract_date_from_record(r) == d]

    # Filter out naps, get main sleep only
    main_sleep = [r for r in records if not r.get("nap", False)]
    if not main_sleep:
        main_sleep = records  # fallback to whatever we have

    if not main_sleep:
        return {"date": d, "data": None, "message": "No sleep data"}

    result = _extract_sleep(main_sleep[0])
    result["date"] = d
    return result


def fetch_strain(conn, target_date: str = None) -> dict:
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    start = f"{d}T00:00:00.000Z"
    end = f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    records = _paginate_all(token, "/cycle", start, end)
    if not records:
        data = _api_get(token, "/cycle", {"limit": 10})
        records = data.get("records", [])
        records = [r for r in records if _extract_date_from_record(r) == d]

    if not records:
        return {"date": d, "data": None, "message": "No cycle data"}

    result = _extract_strain(records[0])
    result["date"] = d
    return result


def fetch_all_daily(conn, target_date: str = None) -> dict:
    """Fetch recovery + sleep + strain — returns ALL available fields."""
    d = target_date or date.today().isoformat()

    recovery = fetch_recovery(conn, d)
    if "error" in recovery:
        return recovery

    sleep = fetch_sleep(conn, d)
    strain = fetch_strain(conn, d)

    # Merge everything into one dict
    result = {"date": d}
    # Recovery fields
    for key in ["recovery_score", "hrv", "rhr", "spo2", "skin_temp"]:
        result[key] = recovery.get(key)
    # Sleep fields
    for key in ["sleep_hours", "sleep_performance", "sleep_efficiency", "sleep_consistency",
                 "respiratory_rate", "rem_hours", "deep_sleep_hours", "light_sleep_hours",
                 "time_in_bed_hours", "disturbances", "sleep_cycles",
                 "sleep_needed_hours", "sleep_debt_hours"]:
        result[key] = sleep.get(key)
    # Strain fields
    for key in ["strain", "calories_burned", "avg_hr", "max_hr"]:
        result[key] = strain.get(key)

    return result


def fetch_bulk(conn, days: int = 10) -> list:
    """Fetch all WHOOP data for the last N days in bulk."""
    token = _get_valid_token(conn)
    if not token:
        return [{"error": "Not authenticated"}]

    end_d = date.today()
    start_d = end_d - timedelta(days=days)
    start = f"{start_d.isoformat()}T00:00:00.000Z"
    end = f"{(end_d + timedelta(days=1)).isoformat()}T00:00:00.000Z"

    recovery_records = _paginate_all(token, "/recovery", start, end)
    sleep_records = _paginate_all(token, "/activity/sleep", start, end)
    cycle_records = _paginate_all(token, "/cycle", start, end)

    # Index by date — include all records, even unscored
    recovery_by_date = {}
    for r in recovery_records:
        d = _extract_date_from_record(r)
        recovery_by_date[d] = _extract_recovery(r)

    sleep_by_date = {}
    for r in sleep_records:
        if r.get("nap", False):
            continue  # skip naps
        d = _extract_date_from_record(r)
        sleep_by_date[d] = _extract_sleep(r)

    strain_by_date = {}
    for r in cycle_records:
        d = _extract_date_from_record(r)
        strain_by_date[d] = _extract_strain(r)

    all_dates = set(list(recovery_by_date.keys()) + list(sleep_by_date.keys()) + list(strain_by_date.keys()))
    results = []
    for d in sorted(all_dates):
        rec = recovery_by_date.get(d, {})
        slp = sleep_by_date.get(d, {})
        cyl = strain_by_date.get(d, {})

        entry = {"date": d}
        # Recovery
        for key in ["recovery_score", "hrv", "rhr", "spo2", "skin_temp"]:
            entry[key] = rec.get(key)
        # Sleep
        for key in ["sleep_hours", "sleep_performance", "sleep_efficiency", "sleep_consistency",
                     "respiratory_rate", "rem_hours", "deep_sleep_hours", "light_sleep_hours",
                     "time_in_bed_hours", "disturbances", "sleep_cycles",
                     "sleep_needed_hours", "sleep_debt_hours"]:
            entry[key] = slp.get(key)
        # Strain
        for key in ["strain", "calories_burned", "avg_hr", "max_hr"]:
            entry[key] = cyl.get(key)

        results.append(entry)

    return results

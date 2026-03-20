"""WHOOP API integration for MCP server.

OAuth2 flow:
1. Call whoop_start_auth → get URL → user opens in browser
2. WHOOP redirects with code → call whoop_complete_auth with the code
3. Tokens stored in DB, auto-refreshed on every API call

Required env vars:
  WHOOP_CLIENT_ID
  WHOOP_CLIENT_SECRET
  WHOOP_REDIRECT_URI  (default: http://localhost:8000/whoop/callback)
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
    """Generate WHOOP OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
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
    """Refresh expired access token."""
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
    """Save OAuth tokens to database."""
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
        return  # Already have tokens

    refresh = os.getenv("WHOOP_REFRESH_TOKEN", "")
    if not refresh:
        return

    try:
        data = _refresh_tokens(refresh)
        save_tokens(conn, data)
    except Exception:
        pass


def _get_valid_token(conn) -> str:
    """Get valid access token, auto-refreshing if needed."""
    _bootstrap_from_env(conn)

    row = conn.execute("SELECT * FROM whoop_tokens WHERE id = 1").fetchone()
    if not row:
        return None

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # Still valid (with 1 min buffer)
    if datetime.now(timezone.utc) < expires_at - timedelta(minutes=1):
        return row["access_token"]

    # Refresh
    try:
        data = _refresh_tokens(row["refresh_token"])
        save_tokens(conn, data)
        return data["access_token"]
    except Exception:
        return None


def is_connected(conn) -> bool:
    """Check if WHOOP is authenticated."""
    return _get_valid_token(conn) is not None


def _api_get(token: str, path: str, params: dict = None) -> dict:
    """Authenticated GET to WHOOP API."""
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


def _paginate_all(token: str, path: str, start: str, end: str) -> list:
    """Fetch all records from a paginated WHOOP endpoint."""
    all_records = []
    params = {"start": start, "end": end, "limit": 25}
    while True:
        data = _api_get(token, path, params)
        if "error" in data:
            break
        records = data.get("records", [])
        all_records.extend(records)
        next_token = data.get("next_token")
        if not next_token or not records:
            break
        params["nextToken"] = next_token
    return all_records


def _extract_date_from_record(record: dict) -> str:
    """Extract the calendar date from a WHOOP record's start/created_at timestamp."""
    for field in ["start", "created_at"]:
        if field in record and record[field]:
            return record[field][:10]
    return date.today().isoformat()


def fetch_recovery(conn, target_date: str = None) -> dict:
    """Fetch recovery data for a date."""
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    start = f"{d}T00:00:00.000Z"
    end = f"{(date.fromisoformat(d) + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    records = _paginate_all(token, "/recovery", start, end)
    if not records:
        # Try without date filter and find matching date
        data = _api_get(token, "/recovery", {"limit": 10})
        records = data.get("records", [])
        # Find record matching our target date
        records = [r for r in records if _extract_date_from_record(r) == d]

    if not records:
        return {"date": d, "data": None, "message": "No recovery data"}

    rec = records[0]
    score = rec.get("score", {})
    return {
        "date": d,
        "recovery_score": score.get("recovery_score"),
        "hrv": score.get("hrv_rmssd_milli"),
        "rhr": score.get("resting_heart_rate"),
        "spo2": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
    }


def fetch_sleep(conn, target_date: str = None) -> dict:
    """Fetch sleep data for a date."""
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

    if not records:
        return {"date": d, "data": None, "message": "No sleep data"}

    score = records[0].get("score", {})
    stages = score.get("stage_summary", {})
    total_sleep_ms = (stages.get("total_in_bed_time_milli", 0)
                      - stages.get("total_awake_time_milli", 0))

    return {
        "date": d,
        "sleep_hours": round(total_sleep_ms / 3600000, 1),
        "sleep_performance": score.get("sleep_performance_percentage"),
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "rem_hours": round(stages.get("total_rem_sleep_time_milli", 0) / 3600000, 1),
        "deep_sleep_hours": round(stages.get("total_slow_wave_sleep_time_milli", 0) / 3600000, 1),
        "disturbances": stages.get("disturbance_count"),
    }


def fetch_strain(conn, target_date: str = None) -> dict:
    """Fetch daily strain from WHOOP cycles."""
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

    score = records[0].get("score", {})
    return {
        "date": d,
        "strain": score.get("strain"),
        "calories": round(score.get("kilojoule", 0) * 0.239006),
        "avg_hr": score.get("average_heart_rate"),
        "max_hr": score.get("max_heart_rate"),
    }


def fetch_all_daily(conn, target_date: str = None) -> dict:
    """Fetch recovery + sleep + strain unified."""
    d = target_date or date.today().isoformat()

    recovery = fetch_recovery(conn, d)
    if "error" in recovery:
        return recovery

    sleep = fetch_sleep(conn, d)
    strain = fetch_strain(conn, d)

    return {
        "date": d,
        "recovery_score": recovery.get("recovery_score"),
        "hrv": recovery.get("hrv"),
        "rhr": recovery.get("rhr"),
        "spo2": recovery.get("spo2"),
        "skin_temp": recovery.get("skin_temp"),
        "sleep_hours": sleep.get("sleep_hours"),
        "sleep_performance": sleep.get("sleep_performance"),
        "respiratory_rate": sleep.get("respiratory_rate"),
        "strain": strain.get("strain"),
        "calories_burned": strain.get("calories"),
        "avg_hr": strain.get("avg_hr"),
        "max_hr": strain.get("max_hr"),
    }


def fetch_bulk(conn, days: int = 10) -> list:
    """Fetch all WHOOP data for the last N days in bulk (fewer API calls)."""
    token = _get_valid_token(conn)
    if not token:
        return [{"error": "Not authenticated"}]

    end_d = date.today()
    start_d = end_d - timedelta(days=days)
    start = f"{start_d.isoformat()}T00:00:00.000Z"
    end = f"{(end_d + timedelta(days=1)).isoformat()}T00:00:00.000Z"

    # Fetch all data in bulk
    recovery_records = _paginate_all(token, "/recovery", start, end)
    sleep_records = _paginate_all(token, "/activity/sleep", start, end)
    cycle_records = _paginate_all(token, "/cycle", start, end)

    # Index by date
    recovery_by_date = {}
    for r in recovery_records:
        d = _extract_date_from_record(r)
        if r.get("score"):
            recovery_by_date[d] = r["score"]

    sleep_by_date = {}
    for r in sleep_records:
        d = _extract_date_from_record(r)
        if r.get("score"):
            sleep_by_date[d] = r["score"]

    strain_by_date = {}
    for r in cycle_records:
        d = _extract_date_from_record(r)
        if r.get("score"):
            strain_by_date[d] = r["score"]

    # Build unified daily records
    all_dates = set(list(recovery_by_date.keys()) + list(sleep_by_date.keys()) + list(strain_by_date.keys()))
    results = []
    for d in sorted(all_dates):
        rec = recovery_by_date.get(d, {})
        slp = sleep_by_date.get(d, {})
        stages = slp.get("stage_summary", {})
        cyl = strain_by_date.get(d, {})

        total_sleep_ms = (stages.get("total_in_bed_time_milli", 0)
                          - stages.get("total_awake_time_milli", 0))

        results.append({
            "date": d,
            "recovery_score": rec.get("recovery_score"),
            "hrv": rec.get("hrv_rmssd_milli"),
            "rhr": rec.get("resting_heart_rate"),
            "spo2": rec.get("spo2_percentage"),
            "skin_temp": rec.get("skin_temp_celsius"),
            "sleep_hours": round(total_sleep_ms / 3600000, 1) if total_sleep_ms else None,
            "sleep_performance": slp.get("sleep_performance_percentage"),
            "respiratory_rate": slp.get("respiratory_rate"),
            "strain": cyl.get("strain"),
            "calories_burned": round(cyl.get("kilojoule", 0) * 0.239006) if cyl.get("kilojoule") else None,
            "avg_hr": cyl.get("average_heart_rate"),
            "max_hr": cyl.get("max_heart_rate"),
        })

    return results

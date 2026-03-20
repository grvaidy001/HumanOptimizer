"""WHOOP API integration for MCP server.

Token lifecycle:
1. User auths via OAuth → callback saves access_token + refresh_token to DB
2. Access token expires after 1 hour
3. On expiry, refresh_token is used to get a new pair (WHOOP rotates both)
4. New tokens saved to DB immediately
5. If DB is empty on startup, tries WHOOP_REFRESH_TOKEN env var as fallback
"""

import os
import urllib.parse
from datetime import datetime, timedelta, date, timezone

import requests

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v2"

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
    """Exchange OAuth code for tokens."""
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _do_refresh(refresh_token: str) -> dict:
    """Refresh tokens. Returns token dict or raises."""
    print(f"WHOOP: Attempting refresh with token ending ...{refresh_token[-8:]}")
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }, timeout=15)

    if resp.status_code != 200:
        print(f"WHOOP: Refresh failed: {resp.status_code} {resp.text[:200]}")
        raise Exception(f"Refresh failed: {resp.status_code}")

    data = resp.json()
    print(f"WHOOP: Refresh succeeded, new token expires in {data.get('expires_in')}s")
    return data


def save_tokens(conn, token_data: dict):
    """Save tokens to database."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=token_data.get("expires_in", 3600))
    access = token_data["access_token"]
    refresh = token_data["refresh_token"]
    expires_str = expires.isoformat()

    # Delete first, then insert (works on both SQLite and Postgres without upsert issues)
    try:
        conn.execute("DELETE FROM whoop_tokens WHERE id = 1")
        conn.execute("""
            INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scopes)
            VALUES (1, ?, ?, ?, ?)
        """, (access, refresh, expires_str, token_data.get("scope", SCOPES)))
        conn.commit()

        # Verify
        row = conn.execute("SELECT id, expires_at FROM whoop_tokens WHERE id = 1").fetchone()
        if row:
            print(f"WHOOP: Tokens saved to DB, expires: {row['expires_at']}")
        else:
            print("WHOOP: ERROR - tokens not found after save!")
    except Exception as e:
        print(f"WHOOP: ERROR saving tokens: {e}")
        try:
            conn.commit()  # commit the DELETE at least
        except Exception:
            pass
        raise


def _get_valid_token(conn) -> str:
    """Get a valid access token. Refreshes if expired. Returns None if unable."""
    # Check DB first
    row = conn.execute("SELECT * FROM whoop_tokens WHERE id = 1").fetchone()

    # If no tokens in DB, try env var
    if not row:
        env_refresh = os.getenv("WHOOP_REFRESH_TOKEN", "")
        if env_refresh:
            print("WHOOP: No tokens in DB, trying WHOOP_REFRESH_TOKEN env var")
            try:
                data = _do_refresh(env_refresh)
                save_tokens(conn, data)
                return data["access_token"]
            except Exception as e:
                print(f"WHOOP: Env var refresh failed: {e}")
                return None
        print("WHOOP: No tokens in DB and no env var")
        return None

    # Check if token is still valid
    expires_at = row["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if now < expires_at - timedelta(minutes=2):
        return row["access_token"]

    # Token expired — refresh
    print(f"WHOOP: Token expired at {expires_at} (now: {now}), refreshing...")
    try:
        data = _do_refresh(row["refresh_token"])
        save_tokens(conn, data)
        return data["access_token"]
    except Exception as e:
        # DB refresh token might be stale, try env var as last resort
        env_refresh = os.getenv("WHOOP_REFRESH_TOKEN", "")
        if env_refresh and env_refresh != row["refresh_token"]:
            print("WHOOP: DB refresh failed, trying env var as last resort")
            try:
                data = _do_refresh(env_refresh)
                save_tokens(conn, data)
                return data["access_token"]
            except Exception as e2:
                print(f"WHOOP: Env var refresh also failed: {e2}")
        return None


def is_connected(conn) -> bool:
    return _get_valid_token(conn) is not None


def _api_get(token: str, path: str, params: dict = None) -> dict:
    """Authenticated GET to WHOOP API."""
    url = f"{API_BASE}{path}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params or {}, timeout=15)

    if resp.status_code == 404:
        return {"records": []}
    if resp.status_code == 401:
        return {"error": "Token expired or invalid", "status": 401}

    # Handle empty responses
    if not resp.text or not resp.text.strip():
        print(f"WHOOP: Empty response from {path}")
        return {"records": []}

    try:
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"WHOOP: API error on {path}: {resp.status_code} {resp.text[:200]}")
        return {"records": [], "error": str(e)}


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
    for field in ["end", "start", "created_at"]:
        if field in record and record[field]:
            return record[field][:10]
    return date.today().isoformat()


def _extract_recovery(rec: dict) -> dict:
    score = rec.get("score") or {}
    return {
        "recovery_score": score.get("recovery_score"),
        "hrv": score.get("hrv_rmssd_milli"),
        "rhr": score.get("resting_heart_rate"),
        "spo2": score.get("spo2_percentage"),
        "skin_temp": score.get("skin_temp_celsius"),
        "score_state": rec.get("score_state"),
    }


def _extract_sleep(rec: dict) -> dict:
    score = rec.get("score") or {}
    stages = score.get("stage_summary") or {}
    sleep_needed = score.get("sleep_needed") or {}

    total_in_bed = stages.get("total_in_bed_time_milli", 0) or 0
    total_awake = stages.get("total_awake_time_milli", 0) or 0
    total_sleep_ms = total_in_bed - total_awake
    total_rem = stages.get("total_rem_sleep_time_milli", 0) or 0
    total_sws = stages.get("total_slow_wave_sleep_time_milli", 0) or 0
    total_light = stages.get("total_light_sleep_time_milli", 0) or 0

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
    score = rec.get("score") or {}
    return {
        "strain": score.get("strain"),
        "kilojoule": score.get("kilojoule"),
        "calories_burned": round(score["kilojoule"] * 0.239006) if score.get("kilojoule") else None,
        "avg_hr": score.get("average_heart_rate"),
        "max_hr": score.get("max_heart_rate"),
        "score_state": rec.get("score_state"),
    }


# ============================================================
# FETCH FUNCTIONS
# ============================================================

def fetch_recovery(conn, target_date: str = None) -> dict:
    """Fetch recovery — uses per-cycle endpoint (more reliable)."""
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    target = date.fromisoformat(d)
    start = f"{(target - timedelta(days=1)).isoformat()}T12:00:00.000Z"
    end = f"{(target + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    # Get cycles first (this always works)
    cycles = _paginate_all(token, "/cycle", start, end)

    # Try per-cycle recovery (most reliable)
    for cycle in cycles:
        cycle_id = cycle.get("id")
        if not cycle_id:
            continue
        try:
            rec_data = _api_get(token, f"/cycle/{cycle_id}/recovery", {})
            if "error" not in rec_data and rec_data.get("score"):
                result = _extract_recovery(rec_data)
                result["date"] = d
                return result
        except Exception:
            continue

    # Fallback: try collection endpoint
    try:
        data = _api_get(token, "/recovery", {"limit": 5})
        records = data.get("records", [])
        for r in records:
            rd = _extract_date_from_record(r)
            if rd == d or rd == (target - timedelta(days=1)).isoformat():
                result = _extract_recovery(r)
                result["date"] = d
                return result
    except Exception:
        pass

    return {"date": d, "data": None, "message": "No recovery data"}


def fetch_sleep(conn, target_date: str = None) -> dict:
    """Fetch sleep — tries collection, then per-sleep-id from recovery."""
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    target = date.fromisoformat(d)
    start = f"{(target - timedelta(days=1)).isoformat()}T12:00:00.000Z"
    end = f"{(target + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    # Try collection endpoint
    records = _paginate_all(token, "/activity/sleep", start, end)
    main_records = [r for r in records if not r.get("nap", False)]
    if not main_records:
        main_records = records

    for r in main_records:
        rd = _extract_date_from_record(r)
        if rd == d or rd == (target - timedelta(days=1)).isoformat():
            if r.get("score"):
                result = _extract_sleep(r)
                result["date"] = d
                return result

    # Fallback: get sleep_id from recovery via cycle
    cycles = _paginate_all(token, "/cycle", start, end)
    for cycle in cycles:
        cycle_id = cycle.get("id")
        if not cycle_id:
            continue
        try:
            rec_data = _api_get(token, f"/cycle/{cycle_id}/recovery", {})
            sleep_id = rec_data.get("sleep_id")
            if sleep_id:
                sleep_data = _api_get(token, f"/activity/sleep/{sleep_id}", {})
                if "error" not in sleep_data and sleep_data.get("score"):
                    result = _extract_sleep(sleep_data)
                    result["date"] = d
                    return result
        except Exception:
            continue

    # Last resort: latest sleep record
    try:
        data = _api_get(token, "/activity/sleep", {"limit": 3})
        for r in data.get("records", []):
            if not r.get("nap", False) and r.get("score"):
                result = _extract_sleep(r)
                result["date"] = d
                return result
    except Exception:
        pass

    return {"date": d, "data": None, "message": "No sleep data"}


def fetch_strain(conn, target_date: str = None) -> dict:
    """Fetch strain from cycles."""
    token = _get_valid_token(conn)
    if not token:
        return {"error": "Not authenticated. Call whoop_start_auth first."}

    d = target_date or date.today().isoformat()
    target = date.fromisoformat(d)
    start = f"{(target - timedelta(days=1)).isoformat()}T12:00:00.000Z"
    end = f"{(target + timedelta(days=1)).isoformat()}T23:59:59.999Z"

    records = _paginate_all(token, "/cycle", start, end)
    for r in records:
        rd = _extract_date_from_record(r)
        if rd == d or rd == (target - timedelta(days=1)).isoformat():
            if r.get("score"):
                result = _extract_strain(r)
                result["date"] = d
                return result

    # Fallback
    try:
        data = _api_get(token, "/cycle", {"limit": 3})
        for r in data.get("records", []):
            if r.get("score"):
                result = _extract_strain(r)
                result["date"] = d
                return result
    except Exception:
        pass

    return {"date": d, "data": None, "message": "No cycle data"}


def fetch_all_daily(conn, target_date: str = None) -> dict:
    """Fetch recovery + sleep + strain — returns ALL available fields."""
    d = target_date or date.today().isoformat()

    recovery = fetch_recovery(conn, d)
    if "error" in recovery:
        return recovery

    sleep = fetch_sleep(conn, d)
    strain = fetch_strain(conn, d)

    result = {"date": d}
    for key in ["recovery_score", "hrv", "rhr", "spo2", "skin_temp"]:
        result[key] = recovery.get(key)
    for key in ["sleep_hours", "sleep_performance", "sleep_efficiency", "sleep_consistency",
                 "respiratory_rate", "rem_hours", "deep_sleep_hours", "light_sleep_hours",
                 "time_in_bed_hours", "disturbances", "sleep_cycles",
                 "sleep_needed_hours", "sleep_debt_hours"]:
        result[key] = sleep.get(key)
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

    # Get all cycles (always works)
    cycle_records = _paginate_all(token, "/cycle", start, end)

    # Build per-cycle data
    results = []
    for cycle in cycle_records:
        cycle_id = cycle.get("id")
        d = _extract_date_from_record(cycle)
        if not cycle_id:
            continue

        entry = {"date": d}

        # Strain from cycle
        if cycle.get("score"):
            s = _extract_strain(cycle)
            for k in ["strain", "calories_burned", "avg_hr", "max_hr"]:
                entry[k] = s.get(k)

        # Recovery per cycle
        try:
            rec = _api_get(token, f"/cycle/{cycle_id}/recovery", {})
            if rec.get("score"):
                r = _extract_recovery(rec)
                for k in ["recovery_score", "hrv", "rhr", "spo2", "skin_temp"]:
                    entry[k] = r.get(k)

                # Sleep from recovery's sleep_id
                sleep_id = rec.get("sleep_id")
                if sleep_id:
                    slp = _api_get(token, f"/activity/sleep/{sleep_id}", {})
                    if slp.get("score"):
                        sl = _extract_sleep(slp)
                        for k in ["sleep_hours", "sleep_performance", "sleep_efficiency",
                                   "sleep_consistency", "respiratory_rate", "rem_hours",
                                   "deep_sleep_hours", "light_sleep_hours", "time_in_bed_hours",
                                   "disturbances", "sleep_cycles", "sleep_needed_hours",
                                   "sleep_debt_hours"]:
                            entry[k] = sl.get(k)
        except Exception:
            pass

        results.append(entry)

    return results

"""Combined server: MCP (streamable-http) + WHOOP webhooks.

For cloud deployment, this runs both:
1. MCP server at /mcp (Claude connects here)
2. WHOOP webhook receiver at /whoop/webhook (WHOOP pushes here)
3. WHOOP OAuth callback at /whoop/callback

For local development, use mcp_server.py directly (stdio transport).
"""

import os
import sys
import json
import hmac
import hashlib
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from app.db import init_db, get_connection, sync_if_turso

init_db()

app = FastAPI(title="HumanOptimizer")

# ============================================================
# WHOOP WEBHOOK
# ============================================================

WHOOP_WEBHOOK_SECRET = os.getenv("WHOOP_WEBHOOK_SECRET", "")

WHOOP_EVENT_MAP = {
    "recovery.updated": "recovery",
    "recovery.created": "recovery",
    "sleep.updated": "sleep",
    "sleep.created": "sleep",
    "workout.updated": "workout",
    "workout.created": "workout",
}


@app.post("/whoop/webhook")
async def whoop_webhook(request: Request):
    """Receive WHOOP webhook events.

    WHOOP pushes these events automatically:
    - recovery.created / recovery.updated
    - sleep.created / sleep.updated
    - workout.created / workout.updated

    When received, we pull the full data for that date and save it.
    """
    body = await request.body()

    # Verify signature if secret is configured
    if WHOOP_WEBHOOK_SECRET:
        signature = request.headers.get("x-whoop-signature", "")
        expected = hmac.new(
            WHOOP_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    event_type = payload.get("type", "")
    event_data = payload.get("data", {})

    if event_type not in WHOOP_EVENT_MAP:
        return JSONResponse({"status": "ignored", "event": event_type})

    # Pull full data for the date and save
    from app.providers.whoop import fetch_all_daily, is_connected

    conn = get_connection()
    if not is_connected(conn):
        conn.close()
        return JSONResponse({"error": "WHOOP not authenticated"}, status_code=401)

    # Extract date from the event
    event_date = None
    for field in ["created_at", "updated_at", "start"]:
        if field in event_data:
            event_date = event_data[field][:10]  # "2026-03-20T..." → "2026-03-20"
            break
    if not event_date:
        event_date = date.today().isoformat()

    data = fetch_all_daily(conn, event_date)
    if "error" not in data:
        conn.execute("""
            INSERT OR REPLACE INTO whoop_daily
            (date, recovery_score, hrv, rhr, sleep_score, sleep_hours, strain,
             calories_burned, avg_hr, max_hr, respiratory_rate, spo2, skin_temp, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_date, data.get("recovery_score"), data.get("hrv"), data.get("rhr"),
              data.get("sleep_performance"), data.get("sleep_hours"), data.get("strain"),
              data.get("calories_burned"), data.get("avg_hr"), data.get("max_hr"),
              data.get("respiratory_rate"), data.get("spo2"), data.get("skin_temp"),
              json.dumps(data)))
        conn.commit()

        # Also update daily_logs
        existing = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (event_date,)).fetchone()
        if existing:
            updates = []
            params = []
            if data.get("recovery_score") is not None:
                updates.append("recovery = ?")
                params.append(data["recovery_score"])
            if data.get("strain") is not None:
                updates.append("strain = ?")
                params.append(int(data["strain"]))
            if data.get("sleep_performance") is not None:
                updates.append("sleep_score = ?")
                params.append(data["sleep_performance"])
            if data.get("rhr") is not None:
                updates.append("rhr = ?")
                params.append(data["rhr"])
            if data.get("hrv") is not None:
                updates.append("hrv = ?")
                params.append(int(data["hrv"]))
            if updates:
                params.append(event_date)
                conn.execute(f"UPDATE daily_logs SET {', '.join(updates)} WHERE date = ?", params)
                conn.commit()

        sync_if_turso(conn)

    conn.close()
    return JSONResponse({
        "status": "saved",
        "event": event_type,
        "date": event_date,
        "recovery": data.get("recovery_score") if "error" not in data else None,
    })


# ============================================================
# WHOOP OAUTH CALLBACK
# ============================================================

@app.get("/whoop/callback")
async def whoop_callback(code: str = "", state: str = "", error: str = ""):
    """Handle WHOOP OAuth redirect. Exchanges code for tokens."""
    if error:
        return HTMLResponse(f"<h1>WHOOP Auth Error</h1><p>{error}</p>")

    if not code:
        return HTMLResponse("<h1>Missing code</h1><p>No authorization code received.</p>")

    from app.providers.whoop import exchange_code, save_tokens

    try:
        token_data = exchange_code(code)
        conn = get_connection()
        save_tokens(conn, token_data)
        sync_if_turso(conn)
        conn.close()
        return HTMLResponse("""
            <h1>WHOOP Connected!</h1>
            <p>Your WHOOP account is now linked to HumanOptimizer.</p>
            <p>You can close this window and go back to Claude.</p>
        """)
    except Exception as e:
        return HTMLResponse(f"<h1>Error</h1><p>{str(e)}</p>")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "tools": 36}


# ============================================================
# MOUNT MCP SERVER
# ============================================================

from mcp_server import mcp

# Mount MCP's streamable-http app at /mcp
mcp_app = mcp.streamable_http_app()
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

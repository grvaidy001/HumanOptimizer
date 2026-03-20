"""Combined server: MCP + WHOOP webhooks + OAuth callback.

Adds custom routes to the MCP Starlette app so everything
shares the same lifespan and session manager.
"""

import os
import sys
import json
import hmac
import hashlib
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
import uvicorn

from app.db import init_db, get_connection, sync_if_turso

init_db()

# Import MCP server and add custom routes BEFORE building the app
from mcp_server import mcp

WHOOP_WEBHOOK_SECRET = os.getenv("WHOOP_WEBHOOK_SECRET", "")


async def health(request: Request):
    return JSONResponse({"status": "ok", "tools": 40})


async def whoop_webhook(request: Request):
    body = await request.body()

    if WHOOP_WEBHOOK_SECRET:
        signature = request.headers.get("x-whoop-signature", "")
        expected = hmac.new(
            WHOOP_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    event_type = payload.get("type", "")
    event_data = payload.get("data", {})

    valid_events = {
        "recovery.created", "recovery.updated",
        "sleep.created", "sleep.updated",
        "workout.created", "workout.updated",
    }
    if event_type not in valid_events:
        return JSONResponse({"status": "ignored", "event": event_type})

    from app.providers.whoop import fetch_all_daily, is_connected

    conn = get_connection()
    if not is_connected(conn):
        conn.close()
        return JSONResponse({"error": "WHOOP not authenticated"}, status_code=401)

    event_date = None
    for field in ["created_at", "updated_at", "start"]:
        if field in event_data:
            event_date = event_data[field][:10]
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

        existing = conn.execute("SELECT * FROM daily_logs WHERE date = ?", (event_date,)).fetchone()
        if existing:
            updates, params = [], []
            for key, col in [("recovery_score", "recovery"), ("strain", "strain"),
                             ("sleep_performance", "sleep_score"), ("rhr", "rhr"), ("hrv", "hrv")]:
                if data.get(key) is not None:
                    updates.append(f"{col} = ?")
                    params.append(int(data[key]) if isinstance(data[key], float) else data[key])
            if updates:
                params.append(event_date)
                conn.execute(f"UPDATE daily_logs SET {', '.join(updates)} WHERE date = ?", params)
                conn.commit()

        sync_if_turso(conn)

    conn.close()
    return JSONResponse({"status": "saved", "event": event_type, "date": event_date})


async def whoop_callback(request: Request):
    code = request.query_params.get("code", "")
    error = request.query_params.get("error", "")

    if error:
        return HTMLResponse(f"<h1>WHOOP Auth Error</h1><p>{error}</p>")
    if not code:
        return HTMLResponse("<h1>Missing code</h1>")

    from app.providers.whoop import exchange_code, save_tokens

    try:
        token_data = exchange_code(code)
        conn = get_connection()
        save_tokens(conn, token_data)
        sync_if_turso(conn)
        conn.close()
        return HTMLResponse(
            "<h1>WHOOP Connected!</h1>"
            "<p>Your WHOOP account is now linked. You can close this window.</p>"
        )
    except Exception as e:
        return HTMLResponse(f"<h1>Error</h1><p>{str(e)}</p>")


# Add custom routes to MCP's Starlette app (before streamable_http_app builds it)
mcp._custom_starlette_routes.extend([
    Route("/health", health, methods=["GET"]),
    Route("/whoop/webhook", whoop_webhook, methods=["POST"]),
    Route("/whoop/callback", whoop_callback, methods=["GET"]),
])

# Build the combined app — MCP handles /mcp, our routes handle the rest
# All share the same lifespan (session manager)
app = mcp.streamable_http_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

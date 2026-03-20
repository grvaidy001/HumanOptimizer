"""FastAPI backend for HumanOptimizer."""

from pathlib import Path
from datetime import date
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db import init_db
from app.models import DailyLog, PowerList, SevenFiveHard, CoachingInput
from app.services.daily_service import (
    save_daily_log, get_daily_log,
    save_power_list, get_power_list,
    save_75_hard, get_75_hard,
    get_streak, get_win_rate,
)
from app.services.weekly_service import generate_weekly_summary, get_week_start
from app.coach import generate_daily_plan
from app.providers.whoop import WHOOPProvider
from app.providers.hevy import HevyProvider
from app.providers.config import (
    get_provider_config, save_provider_config, delete_provider_config, list_configured_providers,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="HumanOptimizer", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Daily Log ---

@app.post("/api/daily-log")
def api_save_daily_log(log: DailyLog):
    return save_daily_log(log)


@app.get("/api/daily-log/{target_date}")
def api_get_daily_log(target_date: str):
    log = get_daily_log(target_date)
    if not log:
        raise HTTPException(404, "No log for this date")
    return log


# --- Power List ---

@app.post("/api/power-list")
def api_save_power_list(pl: PowerList):
    return save_power_list(pl)


@app.get("/api/power-list/{target_date}")
def api_get_power_list(target_date: str):
    pl = get_power_list(target_date)
    if not pl:
        raise HTTPException(404, "No power list for this date")
    return pl


# --- 75 Hard ---

@app.post("/api/75-hard")
def api_save_75_hard(data: SevenFiveHard):
    return save_75_hard(data)


@app.get("/api/75-hard/{target_date}")
def api_get_75_hard(target_date: str):
    data = get_75_hard(target_date)
    if not data:
        raise HTTPException(404, "No 75 Hard data for this date")
    return data


# --- Dashboard ---

@app.get("/api/dashboard")
def api_dashboard():
    today = date.today().isoformat()
    return {
        "date": today,
        "power_list": get_power_list(today),
        "daily_log": get_daily_log(today),
        "seven_five_hard": get_75_hard(today),
        "streak": get_streak(),
        "stats": get_win_rate(30),
    }


# --- Coaching ---

@app.post("/api/coaching/plan")
def api_get_plan(input_data: CoachingInput):
    return generate_daily_plan(input_data)


# --- Weekly ---

@app.get("/api/weekly-summary")
def api_weekly_summary():
    return generate_weekly_summary()


@app.get("/api/weekly-summary/{week_start}")
def api_weekly_summary_for_week(week_start: str):
    from datetime import date as dt_date
    ws = dt_date.fromisoformat(week_start)
    return generate_weekly_summary(ws)


# --- Stats ---

@app.get("/api/stats/streak")
def api_streak():
    return {"streak": get_streak()}


@app.get("/api/stats/win-rate")
def api_win_rate(days: int = 30):
    return get_win_rate(days)


# --- Integrations ---

WHOOP_REDIRECT_URI = "http://localhost:8000/api/integrations/whoop/callback"


@app.get("/api/integrations/status")
def api_integrations_status():
    """Show connection status of all providers."""
    whoop = WHOOPProvider()
    hevy = HevyProvider()
    return {
        "whoop": {
            "configured": bool(get_provider_config("whoop").get("client_id")),
            "connected": whoop.is_connected(),
        },
        "hevy": {
            "configured": bool(get_provider_config("hevy").get("api_key")),
            "connected": hevy.is_connected(),
        },
    }


# -- WHOOP --

@app.post("/api/integrations/whoop/configure")
def api_whoop_configure(client_id: str, client_secret: str):
    """Save WHOOP OAuth credentials."""
    save_provider_config("whoop", {
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return {"status": "configured"}


@app.get("/api/integrations/whoop/auth-url")
def api_whoop_auth_url():
    """Get the WHOOP OAuth authorization URL."""
    whoop = WHOOPProvider()
    url = whoop.get_auth_url(WHOOP_REDIRECT_URI)
    return {"url": url}


@app.get("/api/integrations/whoop/callback")
def api_whoop_callback(code: str = "", state: str = ""):
    """OAuth callback — exchanges code for tokens."""
    if not code:
        raise HTTPException(400, "No authorization code provided")
    whoop = WHOOPProvider()
    success = whoop.exchange_code(code, WHOOP_REDIRECT_URI)
    if success:
        return {"status": "connected", "message": "WHOOP connected successfully! You can close this tab."}
    raise HTTPException(400, "Failed to exchange authorization code")


@app.get("/api/integrations/whoop/metrics/{target_date}")
def api_whoop_metrics(target_date: str):
    """Fetch WHOOP metrics for a date."""
    whoop = WHOOPProvider()
    if not whoop.is_connected():
        raise HTTPException(400, "WHOOP not connected")
    metrics = whoop.fetch_daily_metrics(target_date)
    return {
        "date": metrics.date,
        "recovery": metrics.recovery,
        "strain": metrics.strain,
        "sleep_score": metrics.sleep_score,
        "rhr": metrics.rhr,
        "hrv": metrics.hrv,
        "weight": metrics.weight,
    }


@app.delete("/api/integrations/whoop")
def api_whoop_disconnect():
    delete_provider_config("whoop")
    return {"status": "disconnected"}


# -- Hevy --

@app.post("/api/integrations/hevy/configure")
def api_hevy_configure(api_key: str):
    """Save Hevy API key."""
    save_provider_config("hevy", {"api_key": api_key})
    return {"status": "configured"}


@app.get("/api/integrations/hevy/workouts")
def api_hevy_workouts(page: int = 1):
    """Fetch recent workouts from Hevy."""
    hevy = HevyProvider()
    if not hevy.is_connected():
        raise HTTPException(400, "Hevy not connected")
    workouts = hevy.fetch_workouts(page=page)
    return [
        {
            "id": w.id,
            "title": w.title,
            "start_time": w.start_time,
            "end_time": w.end_time,
            "duration_minutes": w.duration_minutes,
            "total_volume_lbs": w.total_volume_lbs,
            "exercises": [
                {
                    "title": ex.title,
                    "sets": [
                        {
                            "type": s.set_type,
                            "weight_lbs": s.weight_lbs,
                            "reps": s.reps,
                            "rpe": s.rpe,
                        }
                        for s in ex.sets
                    ],
                    "top_set": {
                        "weight_lbs": ex.top_set.weight_lbs,
                        "reps": ex.top_set.reps,
                    } if ex.top_set else None,
                }
                for ex in w.exercises
            ],
        }
        for w in workouts
    ]


@app.get("/api/integrations/hevy/workouts/{target_date}")
def api_hevy_workouts_for_date(target_date: str):
    """Fetch workouts for a specific date."""
    hevy = HevyProvider()
    if not hevy.is_connected():
        raise HTTPException(400, "Hevy not connected")
    workouts = hevy.fetch_workouts_for_date(target_date)
    return [
        {
            "id": w.id,
            "title": w.title,
            "duration_minutes": w.duration_minutes,
            "total_volume_lbs": w.total_volume_lbs,
            "exercises": [
                {
                    "title": ex.title,
                    "top_set": {
                        "weight_lbs": ex.top_set.weight_lbs,
                        "reps": ex.top_set.reps,
                    } if ex.top_set else None,
                }
                for ex in w.exercises
            ],
        }
        for w in workouts
    ]


@app.get("/api/integrations/hevy/count")
def api_hevy_count():
    hevy = HevyProvider()
    if not hevy.is_connected():
        raise HTTPException(400, "Hevy not connected")
    return {"workout_count": hevy.fetch_workout_count()}


@app.delete("/api/integrations/hevy")
def api_hevy_disconnect():
    delete_provider_config("hevy")
    return {"status": "disconnected"}


# --- Static Frontend ---

STATIC_DIR = Path(__file__).parent.parent / "static"


from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
def serve_index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

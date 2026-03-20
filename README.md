# HumanOptimizer — Personal Execution OS

A local-first daily execution system built for aggressive body transformation and discipline tracking. Inspired by 75 Hard and LiveHard.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run (Windows)
run.bat

# 3. Run (Mac/Linux)
chmod +x run.sh && ./run.sh
```

- **Frontend:** http://localhost:8501
- **Backend API:** http://localhost:8000/docs

## What It Does

- **Power List** — 5 daily tasks. Complete all 5 = WIN. Anything less = LOSS.
- **Fitness Tracking** — Weight, fasting cycle, recovery metrics, walking.
- **Coaching Engine** — Rule-based daily plan based on recovery, fasting state, and previous performance.
- **75 Hard Tracker** — Track all 6 daily 75 Hard requirements.
- **Communication Development** — Track practice minutes and sessions.
- **Weekly Review** — Win/loss stats, weight trends, consistency metrics.

## Architecture

```
/app
  main.py          # FastAPI backend
  db.py            # SQLite database
  models.py        # Pydantic models
  coach.py         # Rule-based coaching engine
  services/        # Business logic
  providers/       # Fitness data integrations (manual + stubs)
/frontend
  app.py           # Streamlit UI
/data
  humanoptimizer.db  # SQLite (auto-created)
```

## Test First

1. Open http://localhost:8501
2. Go to **Today** page
3. Fill in your weight and recovery metrics
4. Check off Power List tasks
5. Click **Save Power List** and **Save Daily Log**
6. Click **Get Today's Plan** for coaching recommendation
7. Check out **75 Hard** page

## What's Stubbed for Future

- **Fitness Providers:** Apple Health, Google Fit, Fitbit, WHOOP, Hevy (see `app/providers/stubs.py`)
- **AI Coaching:** `coach.py` is designed to be replaced with Claude/OpenAI calls
- **Mobile App:** Backend API is ready for any frontend
- **Multi-user:** Add auth layer on top of existing API

## Fasting Cycle

The system tracks a rolling 72-hour fast:
- Day 1: FAST
- Day 2: FAST
- Day 3: FAST
- Day 4: REFEED

Training intensity adjusts based on fasting day and recovery signals.

## Day Types

- **Upper** — Upper body strength
- **Lower + Sled** — Lower body + sled work
- **Recovery** — Active recovery only
- **Refeed/Heavy** — Refeed day, push hard

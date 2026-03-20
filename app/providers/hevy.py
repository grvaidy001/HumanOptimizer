"""Hevy API integration.

Uses API key authentication (requires Hevy Pro).
Pulls: workouts, exercises, sets/reps/weight.

Setup:
1. Subscribe to Hevy Pro
2. Go to https://hevy.com/settings?developer
3. Generate an API key
4. Save it via the settings UI
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field

import requests

from app.providers.base import FitnessProvider, FitnessMetrics
from app.providers.config import get_provider_config, save_provider_config

HEVY_API_BASE = "https://api.hevyapp.com"


@dataclass
class HevySet:
    index: int
    set_type: str  # warmup, normal, failure, dropset
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None

    @property
    def weight_lbs(self) -> float | None:
        if self.weight_kg is not None:
            return round(self.weight_kg * 2.20462, 1)
        return None


@dataclass
class HevyExercise:
    index: int
    title: str
    exercise_template_id: str
    notes: str = ""
    sets: list[HevySet] = field(default_factory=list)

    @property
    def total_volume_kg(self) -> float:
        vol = 0
        for s in self.sets:
            if s.weight_kg and s.reps:
                vol += s.weight_kg * s.reps
        return vol

    @property
    def top_set(self) -> HevySet | None:
        """Heaviest working set (non-warmup)."""
        working = [s for s in self.sets if s.set_type != "warmup" and s.weight_kg]
        return max(working, key=lambda s: s.weight_kg, default=None)


@dataclass
class HevyWorkout:
    id: str
    title: str
    start_time: str
    end_time: str
    exercises: list[HevyExercise] = field(default_factory=list)
    description: str = ""

    @property
    def duration_minutes(self) -> int:
        try:
            start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            return int((end - start).total_seconds() / 60)
        except (ValueError, TypeError):
            return 0

    @property
    def total_volume_kg(self) -> float:
        return sum(e.total_volume_kg for e in self.exercises)

    @property
    def total_volume_lbs(self) -> float:
        return round(self.total_volume_kg * 2.20462, 1)


class HevyProvider(FitnessProvider):

    def _get_config(self) -> dict:
        return get_provider_config("hevy")

    def _get_headers(self) -> dict:
        config = self._get_config()
        return {"api-key": config.get("api_key", "")}

    def _api_get(self, path: str, params: dict = None) -> dict | None:
        """Make an authenticated GET request to the Hevy API."""
        resp = requests.get(
            f"{HEVY_API_BASE}{path}",
            headers=self._get_headers(),
            params=params,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None

    def fetch_workouts(self, page: int = 1, page_size: int = 10) -> list[HevyWorkout]:
        """Fetch paginated workout list."""
        data = self._api_get("/v1/workouts", {"page": page, "pageSize": page_size})
        if not data or "workouts" not in data:
            return []
        return [self._parse_workout(w) for w in data["workouts"]]

    def fetch_workout(self, workout_id: str) -> HevyWorkout | None:
        """Fetch a single workout by ID."""
        data = self._api_get(f"/v1/workouts/{workout_id}")
        if not data:
            return None
        return self._parse_workout(data)

    def fetch_workouts_for_date(self, date_str: str) -> list[HevyWorkout]:
        """Fetch all workouts for a specific date. Paginates through all results."""
        all_workouts = []
        page = 1
        while True:
            workouts = self.fetch_workouts(page=page, page_size=10)
            if not workouts:
                break
            for w in workouts:
                w_date = w.start_time[:10]
                if w_date == date_str:
                    all_workouts.append(w)
                elif w_date < date_str:
                    # Past the target date, stop paginating
                    return all_workouts
            page += 1
        return all_workouts

    def fetch_workout_count(self) -> int:
        """Fetch total workout count."""
        data = self._api_get("/v1/workouts/count")
        if data:
            return data.get("workout_count", 0)
        return 0

    def fetch_exercise_history(self, exercise_template_id: str,
                                start_date: str = None, end_date: str = None) -> list[dict]:
        """Fetch history for a specific exercise."""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        data = self._api_get(f"/v1/exercise_history/{exercise_template_id}", params)
        if data and "exercise_history" in data:
            return data["exercise_history"]
        return []

    def fetch_exercise_templates(self) -> list[dict]:
        """Fetch all exercise templates (paginated, up to 500)."""
        templates = []
        page = 1
        while True:
            data = self._api_get("/v1/exercise_templates", {"page": page, "pageSize": 100})
            if not data or "exercise_templates" not in data:
                break
            batch = data["exercise_templates"]
            templates.extend(batch)
            if page >= data.get("page_count", 1):
                break
            page += 1
        return templates

    def _parse_workout(self, raw: dict) -> HevyWorkout:
        exercises = []
        for ex in raw.get("exercises", []):
            sets = []
            for s in ex.get("sets", []):
                sets.append(HevySet(
                    index=s.get("index", 0),
                    set_type=s.get("type", "normal"),
                    weight_kg=s.get("weight_kg"),
                    reps=s.get("reps"),
                    rpe=s.get("rpe"),
                ))
            exercises.append(HevyExercise(
                index=ex.get("index", 0),
                title=ex.get("title", ""),
                exercise_template_id=ex.get("exercise_template_id", ""),
                notes=ex.get("notes", ""),
                sets=sets,
            ))
        return HevyWorkout(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            start_time=raw.get("start_time", ""),
            end_time=raw.get("end_time", ""),
            exercises=exercises,
            description=raw.get("description", ""),
        )

    def fetch_daily_metrics(self, date_str: str) -> FitnessMetrics:
        """Fetch workout metrics for a given date.

        Hevy doesn't provide recovery/HRV — only workout data.
        We calculate active_minutes and calories_burned estimate.
        """
        workouts = self.fetch_workouts_for_date(date_str)
        metrics = FitnessMetrics(date=date_str)

        if workouts:
            total_minutes = sum(w.duration_minutes for w in workouts)
            metrics.active_minutes = total_minutes
            # Rough calorie estimate: ~7 cal/min for strength training
            metrics.calories_burned = total_minutes * 7

        return metrics

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        return FitnessMetrics(
            date=raw_data.get("date", ""),
            active_minutes=raw_data.get("active_minutes"),
            calories_burned=raw_data.get("calories_burned"),
        )

    def is_connected(self) -> bool:
        config = self._get_config()
        api_key = config.get("api_key", "")
        if not api_key:
            return False
        # Quick check: try to get workout count
        data = self._api_get("/v1/workouts/count")
        return data is not None

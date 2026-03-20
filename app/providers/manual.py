"""Manual fitness data provider — the default for MVP."""

from app.providers.base import FitnessProvider, FitnessMetrics


class ManualProvider(FitnessProvider):
    """Manual entry provider. User enters data through the UI."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        # Manual provider doesn't fetch — data comes from UI
        return FitnessMetrics(date=date)

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        return FitnessMetrics(**raw_data)

    def is_connected(self) -> bool:
        return True  # Always connected — it's manual

"""Stub providers for future integrations.

These are placeholders. Implement fetch_daily_metrics() and normalize_data()
when ready to integrate with each service.
"""

from app.providers.base import FitnessProvider, FitnessMetrics


class AppleHealthProvider(FitnessProvider):
    """Apple Health integration via HealthKit export or API."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        raise NotImplementedError("Apple Health integration not yet implemented")

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        raise NotImplementedError("Apple Health integration not yet implemented")

    def is_connected(self) -> bool:
        return False


class GoogleFitProvider(FitnessProvider):
    """Google Fit / Health Connect integration."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        raise NotImplementedError("Google Fit integration not yet implemented")

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        raise NotImplementedError("Google Fit integration not yet implemented")

    def is_connected(self) -> bool:
        return False


class FitbitProvider(FitnessProvider):
    """Fitbit Web API integration."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        raise NotImplementedError("Fitbit integration not yet implemented")

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        raise NotImplementedError("Fitbit integration not yet implemented")

    def is_connected(self) -> bool:
        return False


class WHOOPProvider(FitnessProvider):
    """WHOOP API integration for recovery, strain, sleep."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        raise NotImplementedError("WHOOP integration not yet implemented")

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        raise NotImplementedError("WHOOP integration not yet implemented")

    def is_connected(self) -> bool:
        return False


class HevyProvider(FitnessProvider):
    """Hevy workout tracker integration."""

    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        raise NotImplementedError("Hevy integration not yet implemented")

    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        raise NotImplementedError("Hevy integration not yet implemented")

    def is_connected(self) -> bool:
        return False

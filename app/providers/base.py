"""Base provider interface for fitness data integrations.

All providers must implement fetch_daily_metrics() and normalize_data().
This is the extension point for Apple Health, WHOOP, Fitbit, Google Fit, Hevy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FitnessMetrics:
    """Normalized fitness metrics from any provider."""
    date: str
    recovery: Optional[int] = None       # 0-100
    strain: Optional[int] = None         # 0-21
    sleep_score: Optional[int] = None    # 0-100
    rhr: Optional[int] = None            # beats per minute
    hrv: Optional[int] = None            # milliseconds
    steps: Optional[int] = None
    calories_burned: Optional[int] = None
    active_minutes: Optional[int] = None
    weight: Optional[float] = None       # lbs


class FitnessProvider(ABC):
    """Base class for all fitness data providers."""

    @abstractmethod
    def fetch_daily_metrics(self, date: str) -> FitnessMetrics:
        """Fetch metrics for a given date."""
        ...

    @abstractmethod
    def normalize_data(self, raw_data: dict) -> FitnessMetrics:
        """Normalize provider-specific data to standard format."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the provider is connected and authenticated."""
        ...

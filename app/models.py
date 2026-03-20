"""Pydantic models for HumanOptimizer."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class DailyLog(BaseModel):
    date: str = Field(default_factory=lambda: date.today().isoformat())
    weight: Optional[float] = None
    fasting_day: bool = False
    fasting_cycle_day: int = Field(default=1, ge=1, le=4)
    day_type: str = "Upper"  # Upper, Lower + Sled, Recovery, Refeed/Heavy
    recovery: Optional[int] = Field(default=None, ge=0, le=100)
    strain: Optional[int] = Field(default=None, ge=0, le=21)
    sleep_score: Optional[int] = Field(default=None, ge=0, le=100)
    rhr: Optional[int] = None
    hrv: Optional[int] = None
    walk_minutes: int = 0
    vest_weight: float = 0
    communication_minutes: int = 0
    communication_sessions: int = 0
    communication_notes: str = ""
    notes: str = ""


class PowerList(BaseModel):
    date: str = Field(default_factory=lambda: date.today().isoformat())
    task1_name: str = "Gym Workout"
    task1_done: bool = False
    task2_name: str = "Outdoor Walk"
    task2_done: bool = False
    task3_name: str = "Communication Practice"
    task3_done: bool = False
    task4_name: str = "Reading / Reflection"
    task4_done: bool = False
    task5_name: str = "Custom Task"
    task5_done: bool = False
    completed_count: int = 0
    result: str = "PENDING"  # WIN, LOSS, PENDING


class SevenFiveHard(BaseModel):
    date: str = Field(default_factory=lambda: date.today().isoformat())
    workout1: bool = False
    workout2_outdoor: bool = False
    reading_10_pages: bool = False
    water_gallon: bool = False
    diet_followed: bool = False
    progress_photo: bool = False
    all_complete: bool = False


class CoachingInput(BaseModel):
    recovery: Optional[int] = None
    strain: Optional[int] = None
    fasting_day: bool = False
    fasting_cycle_day: int = 1
    day_type: str = "Upper"
    previous_result: str = "PENDING"
    sleep_score: Optional[int] = None
    hrv: Optional[int] = None


class CoachingPlan(BaseModel):
    status: str  # GREEN, YELLOW, RED
    training: str  # push, moderate, recover
    sled: str
    walk: str
    communication_task: str
    warning: str = ""


class WeeklySummary(BaseModel):
    week_start: str
    wins: int = 0
    losses: int = 0
    win_rate: float = 0
    weight_start: Optional[float] = None
    weight_end: Optional[float] = None
    weight_change: Optional[float] = None
    streak: int = 0
    gym_consistency: float = 0
    walk_consistency: float = 0
    communication_consistency: float = 0
    summary: str = ""

"""Pydantic models for simulation control API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SpeedBody(BaseModel):
    speed: float = Field(..., description="One of 1,5,10,30,60,120")


class ModeBody(BaseModel):
    mode: Literal["NORMAL", "MANUAL", "STRESS", "SCENARIO", "REPLAY"] = "MANUAL"


class ScenarioBody(BaseModel):
    scenario: str = "normal"


class InjectBody(BaseModel):
    target_type: Literal["EQUIPMENT", "ZONE", "ROAD", "SYSTEM"]
    target_id: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    duration_sec: int | None = Field(
        default=None,
        description="Simulated seconds until auto-restore; null = until manual restore",
    )
    simulation_time: str | None = None


class DurationPresetBody(BaseModel):
    """Helper: duration presets in simulated minutes."""

    minutes: int | None = None  # None = until restore

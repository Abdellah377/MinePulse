"""Seeded, simulator-only operational variability for haul cycles.

The values in this module control observable stage behaviour.  They are never
persisted as ML features or exposed to production AI/monitoring code.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CycleDynamicsConfig:
    """Small set of plausible prototype operating ranges (simulated seconds)."""

    loading_min_seconds: float = 150.0
    loading_max_seconds: float = 255.0
    dumping_min_seconds: float = 70.0
    dumping_max_seconds: float = 155.0
    waiting_dump_min_seconds: float = 25.0
    waiting_dump_max_seconds: float = 150.0
    truck_factor_min: float = 0.92
    truck_factor_max: float = 1.06
    loader_factor_min: float = 0.92
    loader_factor_max: float = 1.08
    operating_period_minutes: int = 60


@dataclass(frozen=True)
class OperatingConditions:
    """Hidden runtime conditions whose effects remain observable in operations."""

    travel_factor: float
    loader_rate_factor: float


def sample_temporal_factor(rng: random.Random) -> float:
    """Mostly normal operation, with a small explainable right-tail component."""

    draw = rng.random()
    if draw < 0.78:
        return rng.uniform(0.91, 1.04)
    if draw < 0.96:
        return rng.uniform(0.76, 0.91)
    return rng.uniform(0.52, 0.75)


def sample_service_seconds(
    rng: random.Random,
    minimum: float,
    maximum: float,
    persistent_factor: float,
) -> float:
    """Triangular body plus rare mild delay; never creates an unexplained huge jump."""

    seconds = rng.triangular(minimum, maximum, (minimum + maximum) * 0.48)
    draw = rng.random()
    if draw < 0.035:
        seconds *= rng.uniform(1.35, 1.75)
    elif draw < 0.18:
        seconds *= rng.uniform(1.08, 1.28)
    return seconds * persistent_factor


def operating_conditions(
    *,
    seed: int,
    sim_now: datetime,
    asset_token: str,
    period_minutes: int,
) -> OperatingConditions:
    """Return reproducible conditions for one asset and operating period."""

    period_seconds = max(1, period_minutes) * 60
    period_index = int(sim_now.timestamp()) // period_seconds
    token_seed = f"{seed}:{period_index}:{asset_token}"
    rng = random.Random(token_seed)
    return OperatingConditions(
        travel_factor=sample_temporal_factor(rng),
        loader_rate_factor=sample_temporal_factor(rng),
    )


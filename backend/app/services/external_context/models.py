"""Canonical weather context. Missing fields stay null; null means unknown."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeatherStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class WeatherHorizon(str, Enum):
    CURRENT = "CURRENT"
    FORECAST = "FORECAST"


class WeatherObservation(ContractModel):
    horizon: WeatherHorizon = WeatherHorizon.CURRENT
    notObservedFact: bool = False
    temperatureC: float | None = None
    apparentTemperatureC: float | None = None
    humidityPercent: float | None = None
    precipitationMm: float | None = None
    precipitationProbabilityPercent: float | None = None
    windSpeedKmh: float | None = None
    windGustKmh: float | None = None
    windDirectionDeg: float | None = None
    visibilityKm: float | None = None
    weatherCode: int | None = None
    condition: str | None = None
    cloudCoverPercent: float | None = None


class WeatherForecastHour(WeatherObservation):
    horizon: WeatherHorizon = WeatherHorizon.FORECAST
    notObservedFact: bool = True
    validAt: datetime | None = None


class WeatherContext(ContractModel):
    status: WeatherStatus
    provider: str | None = None
    observedAt: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    current: WeatherObservation | None = None
    forecast: list[WeatherForecastHour] = Field(default_factory=list)
    sourceFreshnessSeconds: float | None = None
    unavailableReason: str | None = None
    isDemo: bool = False
    cacheHit: bool = False

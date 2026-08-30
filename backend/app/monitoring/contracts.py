"""Serializable detector output and runtime-only monitoring snapshot contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.ai.contracts import Severity, TriggerType
from app.db.enums import AlertSource
from app.db.models import Alert, Equipment
from app.ml.failure_risk.contracts import FailureRiskPrediction
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import FleetBulkContext


class MonitoringCandidate(BaseModel):
    """A deterministic symptom worth investigating; never a root-cause claim."""

    model_config = ConfigDict(extra="forbid")

    detector_id: str = Field(min_length=1, max_length=100)
    trigger_type: TriggerType
    site_id: int = Field(gt=0)
    shift_id: int | None = Field(default=None, gt=0)
    equipment_id: int | None = Field(default=None, gt=0)
    zone_id: int | None = Field(default=None, gt=0)
    detected_at: datetime
    severity: Severity
    title: str = Field(min_length=1, max_length=220)
    reason: str = Field(min_length=1, max_length=1200)
    metric: str | None = Field(default=None, max_length=120)
    value: JsonValue = None
    threshold: JsonValue = None
    unit: str | None = Field(default=None, max_length=40)
    deduplication_key: str = Field(min_length=1, max_length=240)
    source_alert_id: int | None = Field(default=None, gt=0)
    alert_source: AlertSource = AlertSource.RULE
    predicted_for: datetime | None = None
    context: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Runtime service results shared by detectors during one site cycle."""

    context: OperationalContext
    equipment: list[Equipment]
    fleet: FleetBulkContext
    production: dict[str, list[dict[str, Any]]]
    active_alerts: list[Alert]
    failure_risk: dict[int, FailureRiskPrediction] = field(default_factory=dict)

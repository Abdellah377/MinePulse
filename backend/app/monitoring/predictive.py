"""Attach served predictive signals to a monitoring snapshot.

Failure-Risk V1 is scored once per site cycle. Detectors never rebuild features.
Unsupported equipment types are skipped so future models can be added independently.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from sqlalchemy.orm import Session

from app.db.enums import EquipmentType
from app.monitoring.contracts import MonitoringSnapshot

logger = logging.getLogger(__name__)

FAILURE_RISK_ELIGIBLE_TYPES = (EquipmentType.HAUL_TRUCK,)
FAILURE_RISK_SOURCE = "FAILURE_RISK_V1"


def attach_failure_risk_predictions(session: Session, snapshot: MonitoringSnapshot) -> MonitoringSnapshot:
    """Score eligible haul trucks; never raise into the monitoring loop."""

    try:
        equipment_ids = [
            equipment.equipment_id
            for equipment in snapshot.equipment
            if equipment.type in FAILURE_RISK_ELIGIBLE_TYPES
        ]
        if not equipment_ids:
            return replace(snapshot, failure_risk={})
        from app.ml.failure_risk.inference import score_equipment

        scored = score_equipment(session, equipment_ids, snapshot.context.sim_now)
        return replace(snapshot, failure_risk=scored)
    except Exception:
        site_id = getattr(getattr(snapshot, "context", None), "site_id", None)
        logger.exception(
            "Failure-Risk scoring failed; predictive detector will emit nothing",
            extra={"site_id": site_id},
        )
        try:
            return replace(snapshot, failure_risk={})
        except Exception:
            return snapshot

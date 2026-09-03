"""Alert-type eligibility for the V1 dispatch optimizer."""

from __future__ import annotations

from typing import Any

OPTIMIZABLE = "OPTIMIZABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"

OPTIMIZABLE_ALERT_TYPES = frozenset(
    {
        "CONGESTION_RISK",
        "PRODUCTION_DEVIATION",
        "ROAD_CLOSED",
        "ZONE_CLOSED",
    }
)
OPTIMIZABLE_DETECTORS = frozenset(
    {
        "prolonged-idle-wait",
        "abnormal-cycle-duration",
    }
)


def monitoring_of(alert: Any) -> dict:
    meta = getattr(alert, "metadata_", None) or getattr(alert, "metadata", None) or {}
    if not isinstance(meta, dict):
        return {}
    monitoring = meta.get("monitoring")
    return monitoring if isinstance(monitoring, dict) else {}


def eligibility_for_alert(alert: Any) -> str:
    alert_type = str(getattr(alert, "alert_type", "") or "")
    monitoring = monitoring_of(alert)
    detector = str(monitoring.get("detectorId") or monitoring.get("detector_id") or "")
    if alert_type in OPTIMIZABLE_ALERT_TYPES or detector in OPTIMIZABLE_DETECTORS:
        return OPTIMIZABLE
    if alert_type == "OPERATIONAL_EVENT":
        related = str(monitoring.get("relatedAlertType") or monitoring.get("alert_type") or "")
        payload = monitoring.get("payload") if isinstance(monitoring.get("payload"), dict) else {}
        payload_type = str(payload.get("category") or payload.get("alert_type") or "")
        if related in OPTIMIZABLE_ALERT_TYPES or payload_type in OPTIMIZABLE_ALERT_TYPES or detector in OPTIMIZABLE_DETECTORS:
            return OPTIMIZABLE
        return NOT_APPLICABLE
    return NOT_APPLICABLE

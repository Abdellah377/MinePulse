"""Case-level dispatch scope. Type eligibility is not enough to run the truck optimizer."""

from __future__ import annotations

from typing import Any

from app.optimization.eligibility import (
    NOT_APPLICABLE,
    OPTIMIZABLE,
    OPTIMIZABLE_DETECTORS,
    eligibility_for_alert,
    monitoring_of,
)

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE_TO_DISPATCH = "NOT_APPLICABLE_TO_DISPATCH"

DISPATCH_POSITIVE_ACTIONS = frozenset({"REVIEW_QUEUE_DISTRIBUTION", "CONSIDER_REASSIGNMENT"})
DISPATCH_NEGATIVE_ACTIONS = frozenset({"INSPECT_EQUIPMENT", "ESCALATE_TO_MAINTENANCE", "NO_ACTION"})
ALWAYS_DISPATCH_TYPES = frozenset({"CONGESTION_RISK", "ROAD_CLOSED", "ZONE_CLOSED"})
ZONE_LEVEL_DISPATCH_TYPES = frozenset({"ROAD_CLOSED", "ZONE_CLOSED"})


def inbox_optimization_eligible(alert: Any) -> bool:
    """Inbox badge: type may be dispatch-related AND a usable subject exists."""
    if eligibility_for_alert(alert) != OPTIMIZABLE:
        return False
    if getattr(alert, "equipment_id", None):
        return True
    return str(getattr(alert, "alert_type", "") or "") in ZONE_LEVEL_DISPATCH_TYPES


def _has_authoritative_facts(trusted: Any) -> bool:
    if trusted is None:
        return False
    if getattr(trusted, "truck", None) is None:
        return False
    if not getattr(trusted, "dest_code", None):
        return False
    loaders = list(getattr(trusted, "loaders", None) or [])
    if not loaders:
        return False
    zones = getattr(trusted, "loader_zones", None) or {}
    if not zones:
        return False
    roads = list(getattr(trusted, "roads", None) or [])
    return bool(roads)


def _action_type(investigation: dict | None) -> str:
    if not isinstance(investigation, dict):
        return ""
    recommendation = investigation.get("recommendation")
    if not isinstance(recommendation, dict):
        return ""
    return str(recommendation.get("action_type") or "")


def _diagnosis_status(investigation: dict | None) -> str:
    if not isinstance(investigation, dict):
        return ""
    conclusion = investigation.get("conclusion")
    if not isinstance(conclusion, dict):
        return ""
    return str(conclusion.get("diagnosis_status") or "").upper()


def assess_dispatch_scope(
    *,
    alert: Any,
    trusted: Any,
    investigation: dict | None = None,
) -> str:
    """Decide whether this investigated case has a real truck-dispatch optimization scope.

    Never invents a subject truck. Type-level OPTIMIZABLE is necessary, not sufficient.
    """
    if eligibility_for_alert(alert) != OPTIMIZABLE:
        return NOT_APPLICABLE
    if not _has_authoritative_facts(trusted):
        return NOT_APPLICABLE_TO_DISPATCH

    alert_type = str(getattr(alert, "alert_type", "") or "")
    detector = str(monitoring_of(alert).get("detectorId") or monitoring_of(alert).get("detector_id") or "")
    if alert_type in ALWAYS_DISPATCH_TYPES or detector in OPTIMIZABLE_DETECTORS:
        return APPLICABLE

    action = _action_type(investigation)
    if action in DISPATCH_NEGATIVE_ACTIONS:
        return NOT_APPLICABLE_TO_DISPATCH
    if action in DISPATCH_POSITIVE_ACTIONS:
        return APPLICABLE

    facts = getattr(trusted, "planner_facts", None) or {}
    if facts.get("hasQueueCondition") or facts.get("hasRoadRestrictionOrBlockage"):
        return APPLICABLE
    return NOT_APPLICABLE_TO_DISPATCH

"""Thin evidence adapter over the external-context weather service."""

from __future__ import annotations

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from app.ai.contracts import EvidenceItem, EvidenceKind, EvidenceStatus
from app.services.external_context.models import WeatherStatus
from app.services.external_context.weather import get_weather_context
from app.services.operational.context import OperationalContext

_NOTES = (
    "Supplemental external weather. Current observations are FACT. Forecast hours are "
    "not measured fact. Weather does not rewrite haul-road status and is not automatic "
    "causality for mechanical failure. Authoritative road status still wins."
)


def weather_context(session: Session, ctx: OperationalContext) -> EvidenceItem:
    context = get_weather_context(session, ctx.site_id)
    status_map = {
        WeatherStatus.AVAILABLE: EvidenceStatus.AVAILABLE,
        WeatherStatus.UNAVAILABLE: EvidenceStatus.UNAVAILABLE,
        WeatherStatus.ERROR: EvidenceStatus.ERROR,
    }
    evidence_status = status_map[context.status]
    available = evidence_status == EvidenceStatus.AVAILABLE
    metadata = {
        "contextType": "CURRENT_WEATHER",
        "forecastIsNotObservedFact": True,
        "forecastHorizonHours": len(context.forecast),
        "authoritativeRoadStatusWins": True,
        "weatherStatus": context.status.value,
        "cacheHit": context.cacheHit,
        "isDemo": False,
    }
    return EvidenceItem(
        kind=EvidenceKind.FACT,
        source_tool="weather_context",
        source_service="app.services.external_context.weather.get_weather_context",
        metric="weather_context",
        value=to_jsonable_python(context) if available else None,
        available=available,
        status=evidence_status,
        site_id=ctx.site_id,
        shift_id=ctx.shift_id,
        observed_at=context.observedAt or ctx.sim_now,
        source_record_ids=[f"site:{ctx.site_id}"],
        metadata=to_jsonable_python(metadata),
        notes=_NOTES if available else (context.unavailableReason or _NOTES),
    )

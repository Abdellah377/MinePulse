"""Print the bounded telemetry evidence LangGraph would receive; no LLM or writes.

Run from backend/:
  python scripts/inspect_ai_evidence.py --equipment TRK-001 --group mechanical
  python scripts/inspect_ai_evidence.py --equipment TRK-016 --group fuel
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.ai.contracts import (
    EvidenceRequest,
    EvidenceRequestType,
    InvestigationTrigger,
    TelemetryMetricGroup,
    TriggerSource,
    TriggerType,
)
from app.ai.tools.registry import EvidenceToolRegistry
from app.db.database import SessionLocal
from app.db.models import Alert, Equipment
from app.services.operational.context import get_operational_context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equipment", required=True, help="Persisted equipment code")
    parser.add_argument("--group", choices=[item.value for item in TelemetryMetricGroup], default="equipment")
    parser.add_argument("--site-code")
    parser.add_argument("--shift-id", type=int)
    parser.add_argument("--incident-time", help="ISO timestamp; defaults to the latest equipment alert or operational now")
    args = parser.parse_args()

    with SessionLocal() as session:
        ctx = get_operational_context(session, site_code=args.site_code, shift_id=args.shift_id)
        equipment = session.scalar(
            select(Equipment).where(
                Equipment.site_id == ctx.site_id,
                Equipment.code == args.equipment,
            )
        )
        if equipment is None:
            print(json.dumps({"error": "equipment_not_found", "equipment": args.equipment}))
            return 1
        latest_alert = session.scalar(
            select(Alert)
            .where(Alert.equipment_id == equipment.equipment_id)
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        incident_time = (
            datetime.fromisoformat(args.incident_time)
            if args.incident_time
            else latest_alert.created_at if latest_alert else ctx.sim_now
        )
        trigger_type = (
            TriggerType.CONNECTIVITY_ISSUE
            if args.group == TelemetryMetricGroup.CONNECTIVITY.value
            else TriggerType.MAINTENANCE_RISK
        )
        trigger = InvestigationTrigger(
            trigger_type=trigger_type,
            trigger_source=TriggerSource.USER_INVESTIGATE,
            source="developer-evidence-inspection",
            site_id=ctx.site_id,
            shift_id=ctx.shift_id,
            equipment_id=equipment.equipment_id,
            occurred_at=incident_time,
            source_record_id=(f"alert:{latest_alert.alert_id}" if latest_alert else None),
            payload={},
        )
        evidence = EvidenceToolRegistry(session).gather_initial(ctx, trigger)
        initial_trend = next(
            item for item in evidence if item.source_tool == "equipment_telemetry_trends"
        )
        selected_trend = EvidenceToolRegistry(session).dispatch(
            ctx,
            EvidenceRequest(
                request_type=EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS,
                equipment_id=equipment.equipment_id,
                end_time=incident_time,
                parameters=[args.group],
                reason="Developer read-only evidence inspection.",
            ),
        )
        print(
            json.dumps(
                {
                    "equipment": args.equipment,
                    "incidentTime": incident_time.isoformat(),
                    "initialProviderEvidence": initial_trend.model_dump(mode="json"),
                    "selectedGroupEvidence": selected_trend.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if initial_trend.available and selected_trend.available else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Invoke the real investigation flow using persisted operational context.

From backend/: python scripts/smoke_ai.py --check-only
              python scripts/smoke_ai.py --mock-provider
              python scripts/smoke_ai.py --http-url http://127.0.0.1:8000
Without --mock-provider, execution uses the configured (potentially paid) LLM.
Mock runs are explicitly labelled and use isolated source IDs, never alert IDs.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.ai.contracts import (
    DiagnosisResult, InvestigationConclusion, InvestigationRecommendation,
    InvestigationResult, InvestigationTrigger,
)
from app.ai.llm.provider import create_llm_provider
from app.ai.persistence import get_investigation, record_to_result
from app.ai.persistence import InvestigationPersistenceError
from app.ai.service import run_investigation
from app.config import get_settings
from app.db.database import SessionLocal
from app.services.operational.alerts import list_site_alerts
from app.services.operational.context import get_operational_context


class SmokeProvider:
    """Test double only: never installed as a runtime provider or used by the UI."""
    provider_name = "smoke-test"
    model_name = "no-llm"

    def diagnose(self, payload):
        return DiagnosisResult(can_conclude=False, confidence="LOW",
            confidence_rationale="Smoke test: reasoning was not evaluated.",
            reasoning_summary="Smoke test only; no diagnosis produced.")

    def build_conclusion(self, payload):
        return InvestigationConclusion(summary="Smoke test only; LLM reasoning not evaluated.", confidence="LOW")

    def build_recommendation(self, payload):
        return InvestigationRecommendation(action_type="NO_ACTION",
            description="Smoke test only. Do not use for operational decisions.",
            rationale="No real LLM was invoked.")

    def discuss_recommendation(self, payload):
        from app.ai.contracts import RecommendationDiscussionReply
        return RecommendationDiscussionReply(reply="Smoke discussion only.", cited_evidence_ids=[], operator_claims_unverified=[])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Read-only DB/config checks; no LLM or writes")
    parser.add_argument("--mock-provider", action="store_true", help="Persist an isolated test audit using real operational services")
    parser.add_argument("--http-url", help="Use a running API (cannot combine with --mock-provider)")
    parser.add_argument("--in-process-api", action="store_true", help="Exercise actual FastAPI routes in-process without starting application lifespan")
    parser.add_argument("--summary", action="store_true", help="Print compact structured result instead of full evidence")
    parser.add_argument("--site-code")
    parser.add_argument("--shift-id", type=int)
    args = parser.parse_args()
    if args.http_url and args.mock_provider:
        parser.error("A running API must never accept a mock provider override")
    if args.http_url and args.in_process_api:
        parser.error("Choose either a running API or in-process API")
    logging.basicConfig(level=logging.INFO)
    stage = "database"
    try:
        with SessionLocal() as session:
            settings = get_settings()
            print(json.dumps({"provider": settings.ai_provider, "model": settings.ai_model,
                "api_key_configured": bool(settings.openai_api_key),
                "max_iterations": settings.ai_max_investigation_iterations}))
            inspector = inspect(session.bind)
            has_table = inspector.has_table("ai_investigations")
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalars().all() if inspector.has_table("alembic_version") else []
            print(json.dumps({"investigation_table": has_table, "migration_revisions": revision}))
            stage = "context_resolution"
            ctx = get_operational_context(session, site_code=args.site_code, shift_id=args.shift_id)
            print(json.dumps({"site_id": ctx.site_id, "shift_id": ctx.shift_id, "as_of": ctx.sim_now.isoformat()}))
            stage = "persistence_preflight"
            if not has_table:
                raise RuntimeError("Missing ai_investigations table; run python -m alembic upgrade head")
            # Verify all ORM columns before any paid call.
            from app.ai.persistence import find_investigations
            find_investigations(session, site_id=ctx.site_id, source_record_id="smoke-preflight")
            stage = "provider_configuration"
            provider = SmokeProvider() if args.mock_provider else None if args.http_url else create_llm_provider(settings)
            if args.check_only:
                if args.http_url:
                    create_llm_provider(settings)
                print("Preflight OK; no investigation created.")
                return 0
            alerts = list_site_alerts(session, ctx.site_id, limit=1)
            alert = alerts[0] if alerts else None
            trigger = InvestigationTrigger(
                trigger_type="OPERATIONAL_EVENT" if alert else "PRODUCTION_DEVIATION",
                trigger_source="USER_INVESTIGATE", source="developer-smoke",
                source_record_id=f"smoke-{uuid4()}", site_id=ctx.site_id, shift_id=ctx.shift_id,
                equipment_id=alert.equipment_id if alert else None,
                zone_id=alert.zone_id if alert else None,
                occurred_at=ctx.sim_now,
                payload={"smoke_test": True, "mock_provider": args.mock_provider,
                         "alert_id": alert.alert_id if alert else None},
            )
            stage = "investigation"
            if args.http_url:
                import httpx
                with httpx.Client(base_url=args.http_url, timeout=210) as client:
                    response = client.post("/api/ai/investigations", json=trigger.model_dump(mode="json"))
                    print(f"POST /api/ai/investigations: {response.status_code}")
                    if response.is_error:
                        detail = response.json().get("detail", {})
                        if isinstance(detail, dict):
                            stage = detail.get("stage", stage)
                            print(json.dumps({"code": detail.get("code"), "stage": stage}))
                    response.raise_for_status()
                    result = InvestigationResult.model_validate(response.json())
                    stage = "http_retrieval"
                    saved = client.get(f"/api/ai/investigations/{result.investigation_id}")
                    saved.raise_for_status()
                    assert InvestigationResult.model_validate(saved.json()) == result
            elif args.in_process_api:
                from fastapi.testclient import TestClient
                from unittest.mock import patch
                from app.main import app
                with patch("app.ai.service.create_llm_provider", return_value=provider):
                    # No context manager: do not run the application lifespan/data source.
                    client = TestClient(app)
                    response = client.post("/api/ai/investigations", json=trigger.model_dump(mode="json"))
                    print(f"POST /api/ai/investigations: {response.status_code}")
                    response.raise_for_status()
                    result = InvestigationResult.model_validate(response.json())
                    saved = client.get(f"/api/ai/investigations/{result.investigation_id}")
                    saved.raise_for_status()
                    assert InvestigationResult.model_validate(saved.json()) == result
                    associated = client.get("/api/ai/investigations", params={"site_id": ctx.site_id, "source_record_id": trigger.source_record_id})
                    associated.raise_for_status()
                    assert associated.json()[0]["investigation_id"] == str(result.investigation_id)
                    print("GET by ID and source association OK.")
            else:
                result = run_investigation(session, trigger, provider=provider)
            stage = "persistence_retrieval"
            session.expire_all()
            row = get_investigation(session, result.investigation_id)
            assert row is not None and record_to_result(row) == result
            print(result.model_dump_json(indent=2, exclude={"evidence", "hypotheses", "operational_context"} if args.summary else None))
            print(json.dumps({"evidence_count": len(result.evidence), "evidence_errors": [e.source_tool for e in result.evidence if e.status == "ERROR"]}))
            print("Persistence round-trip OK.")
            return 1 if result.error else 0
    except Exception as exc:
        if isinstance(exc, InvestigationPersistenceError):
            stage = "persistence"
        # No credentials, SQL parameters or provider response bodies in stdout.
        print(json.dumps({"failed_stage": stage, "error_type": type(exc).__name__}))
        if stage in {"persistence_preflight", "provider_configuration"}:
            print("Check migrations and AI_PROVIDER / AI_MODEL / OPENAI_API_KEY; see backend configuration documentation.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

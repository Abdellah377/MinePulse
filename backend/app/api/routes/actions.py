"""Actions IA inbox endpoints. No LLM on list or detail."""

from fastapi import APIRouter, Query

from app.ai.contracts import RecommendationDecisionRequest
from app.ai.feedback import upsert_alert_decision
from app.api.deps import Ctx, DbSession
from app.optimization.inbox import inbox_detail, list_inbox
from app.services.operational.alerts import ALERT_PAGE_DEFAULT, ALERT_PAGE_MAX, _parse_alert_pk

router = APIRouter()


@router.get("/inbox")
def get_inbox(
    session: DbSession,
    ctx: Ctx,
    cursor: str | None = Query(None),
    limit: int = Query(ALERT_PAGE_DEFAULT, ge=1, le=ALERT_PAGE_MAX),
):
    return list_inbox(session, ctx, cursor=cursor, limit=limit)


@router.get("/inbox/{alert_id}")
def get_inbox_detail(alert_id: str, session: DbSession, ctx: Ctx):
    return inbox_detail(session, ctx, alert_id)


@router.put("/inbox/{alert_id}/decision")
def put_inbox_decision(alert_id: str, body: RecommendationDecisionRequest, session: DbSession, ctx: Ctx):
    detail = inbox_detail(session, ctx, alert_id)
    original = {}
    investigation_id = None
    if detail.get("latestRun") and detail["latestRun"].get("recommendedCandidateId"):
        run = detail["latestRun"]
        chosen = next(
            (item for item in run.get("candidates") or [] if item.get("candidateId") == run.get("recommendedCandidateId")),
            None,
        )
        original = chosen or {"runId": run.get("runId"), "outcome": run.get("outcome")}
    inv_id = detail.get("investigationId")
    if inv_id:
        from uuid import UUID
        from app.ai.persistence import get_investigation

        investigation_id = UUID(inv_id)
        investigation = get_investigation(session, investigation_id)
        if investigation is not None and investigation.recommendation:
            original = dict(investigation.recommendation)
    return upsert_alert_decision(
        session,
        _parse_alert_pk(alert_id),
        body,
        site_id=ctx.site_id,
        original_recommendation=original or {"alertId": alert_id},
        investigation_id=investigation_id,
    )

"""Investigation start/retrieve plus operator decision and discussion endpoints."""

from uuid import UUID
from contextlib import contextmanager
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.ai.contracts import (
    DiscussionPostRequest,
    DiscussionThread,
    InvestigationResult,
    InvestigationTrigger,
    RecommendationDecisionRequest,
    RecommendationDecisionRecord,
    RecommendationDecisionView,
)
from app.ai.discussion import post_discussion
from app.ai.feedback import (
    FeedbackConflict,
    FeedbackNotFound,
    get_decision_view,
    get_discussion,
    upsert_decision,
)
from app.ai.llm.provider import ProviderConfigurationError
from app.ai.persistence import InvestigationPersistenceError, find_investigations, get_investigation, record_to_result
from app.ai.service import run_investigation
from app.api.deps import DbSession
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


@contextmanager
def investigation_errors(session, stage: str):
    """Stable safe codes, not arbitrary SQL/SDK exception strings, cross the API."""
    try:
        yield
    except HTTPException:
        raise
    except FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    except FeedbackConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "AI_RECOMMENDATION_REQUIRED", "stage": stage},
        ) from exc
    except ProviderConfigurationError as exc:
        logger.warning("Investigation rejected: provider configuration missing/invalid")
        raise HTTPException(503, detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "stage": "provider_configuration"}) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        code = "AI_STORAGE_NOT_READY" if sqlstate in {"42P01", "42703"} else "AI_STORAGE_UNAVAILABLE"
        logger.error("Investigation storage failure stage=%s type=%s sqlstate=%s", stage, type(exc).__name__, sqlstate)
        raise HTTPException(503, detail={"code": code, "stage": stage}) from exc
    except InvestigationPersistenceError as exc:
        raise HTTPException(500, detail={"code": "AI_PERSISTENCE_FAILED", "stage": "persist"}) from exc
    except Exception as exc:
        session.rollback()
        logger.exception("Investigation API failure stage=%s", stage)
        raise HTTPException(500, detail={"code": "AI_INVESTIGATION_FAILED", "stage": stage}) from exc


@router.post("/investigations", response_model=InvestigationResult)
def start_investigation(trigger: InvestigationTrigger, session: DbSession):
    with investigation_errors(session, "start"):
        return run_investigation(session, trigger)


@router.get("/investigations", response_model=list[InvestigationResult])
def associated_investigations(
    session: DbSession,
    site_id: int = Query(gt=0),
    source_record_id: str = Query(min_length=1, max_length=160),
    shift_id: int | None = Query(default=None, gt=0),
):
    with investigation_errors(session, "lookup"):
        return [record_to_result(row) for row in find_investigations(
            session, site_id=site_id, source_record_id=source_record_id, shift_id=shift_id
        )]


@router.get("/investigations/{investigation_id}", response_model=InvestigationResult)
def retrieve_investigation(investigation_id: UUID, session: DbSession):
    with investigation_errors(session, "retrieve"):
        row = get_investigation(session, investigation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        return record_to_result(row)


@router.get("/investigations/{investigation_id}/debug")
def retrieve_investigation_debug(investigation_id: UUID, session: DbSession):
    if not get_settings().ai_debug_mode:
        raise HTTPException(status_code=403, detail={"code": "AI_DEBUG_DISABLED"})
    with investigation_errors(session, "debug"):
        row = get_investigation(session, investigation_id)
        if row is None or row.debug_trace is None:
            raise HTTPException(status_code=404, detail="Investigation debug trace not found")
        return row.debug_trace


@router.get("/investigations/{investigation_id}/decision", response_model=RecommendationDecisionView)
def retrieve_decision(investigation_id: UUID, session: DbSession):
    with investigation_errors(session, "decision"):
        return get_decision_view(session, investigation_id)


@router.put("/investigations/{investigation_id}/decision", response_model=RecommendationDecisionRecord)
def record_decision(investigation_id: UUID, body: RecommendationDecisionRequest, session: DbSession):
    with investigation_errors(session, "decision"):
        return upsert_decision(session, investigation_id, body)


@router.get("/investigations/{investigation_id}/discussion", response_model=DiscussionThread)
def retrieve_discussion(investigation_id: UUID, session: DbSession):
    with investigation_errors(session, "discussion"):
        return get_discussion(session, investigation_id)


@router.post("/investigations/{investigation_id}/discussion", response_model=DiscussionThread)
def record_discussion(investigation_id: UUID, body: DiscussionPostRequest, session: DbSession):
    with investigation_errors(session, "discussion"):
        return post_discussion(session, investigation_id, body)

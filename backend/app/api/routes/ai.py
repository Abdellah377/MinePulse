"""Minimal non-chat API for starting and retrieving investigations."""

from uuid import UUID
from contextlib import contextmanager
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.ai.contracts import InvestigationResult, InvestigationTrigger
from app.ai.llm.provider import ProviderConfigurationError
from app.ai.persistence import InvestigationPersistenceError, find_investigations, get_investigation, record_to_result
from app.ai.service import run_investigation
from app.api.deps import DbSession

router = APIRouter()
logger = logging.getLogger(__name__)


@contextmanager
def investigation_errors(session, stage: str):
    """Stable safe codes, not arbitrary SQL/SDK exception strings, cross the API."""
    try:
        yield
    except HTTPException:
        raise
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

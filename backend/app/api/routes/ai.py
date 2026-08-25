"""Minimal non-chat API for starting and retrieving investigations."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.ai.contracts import InvestigationResult, InvestigationTrigger
from app.ai.llm.provider import ProviderConfigurationError
from app.ai.persistence import get_investigation, record_to_result
from app.ai.service import run_investigation
from app.api.deps import DbSession

router = APIRouter()


@router.post("/investigations", response_model=InvestigationResult)
def start_investigation(trigger: InvestigationTrigger, session: DbSession):
    try:
        return run_investigation(session, trigger)
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/investigations/{investigation_id}", response_model=InvestigationResult)
def retrieve_investigation(investigation_id: UUID, session: DbSession):
    row = get_investigation(session, investigation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return record_to_result(row)

"""Deterministic optimization runs. No LLM."""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import Ctx, DbSession
from app.optimization.service import create_optimization_run, list_optimization_runs

router = APIRouter()


class OptimizationRunRequest(BaseModel):
    alert_id: str = Field(min_length=1, max_length=80)


@router.post("/runs")
def post_optimization_run(body: OptimizationRunRequest, session: DbSession, ctx: Ctx):
    return create_optimization_run(session, ctx, body.alert_id)


@router.get("/runs")
def get_optimization_runs(session: DbSession, alert_id: str = Query(min_length=1, max_length=80)):
    return list_optimization_runs(session, alert_id)

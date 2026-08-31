"""Immutable optimization-run persistence. No LLM. No operational mutations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ai import AiOptimizationRun


def persist_run(
    session: Session,
    *,
    alert_id: int,
    site_id: int,
    optimizer_version: str,
    weights: dict,
    eligibility: str,
    outcome: str,
    snapshot_digest: str | None,
    candidates: list,
    recommended_candidate_id: str | None,
    weather_status: str | None,
    snapshot: dict,
) -> AiOptimizationRun:
    row = AiOptimizationRun(
        run_id=uuid4(),
        alert_id=alert_id,
        site_id=site_id,
        optimizer_version=optimizer_version,
        weights=dict(weights),
        eligibility=eligibility,
        outcome=outcome,
        snapshot_digest=snapshot_digest,
        candidates=list(candidates),
        recommended_candidate_id=recommended_candidate_id,
        weather_status=weather_status,
        snapshot=dict(snapshot),
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_runs_for_alert(session: Session, alert_id: int, *, limit: int = 10) -> list[AiOptimizationRun]:
    return list(
        session.scalars(
            select(AiOptimizationRun)
            .where(AiOptimizationRun.alert_id == alert_id)
            .order_by(AiOptimizationRun.created_at.desc())
            .limit(limit)
        ).all()
    )


def latest_run_for_alert(session: Session, alert_id: int) -> AiOptimizationRun | None:
    return session.scalar(
        select(AiOptimizationRun)
        .where(AiOptimizationRun.alert_id == alert_id)
        .order_by(AiOptimizationRun.created_at.desc())
        .limit(1)
    )


def run_to_dict(row: AiOptimizationRun) -> dict:
    return {
        "runId": str(row.run_id),
        "alertId": f"alert-{row.alert_id}",
        "siteId": row.site_id,
        "optimizerVersion": row.optimizer_version,
        "weights": row.weights or {},
        "eligibility": row.eligibility,
        "outcome": row.outcome,
        "snapshotDigest": row.snapshot_digest,
        "candidates": row.candidates or [],
        "recommendedCandidateId": row.recommended_candidate_id,
        "weatherStatus": row.weather_status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }

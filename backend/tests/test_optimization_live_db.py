"""Live PostgreSQL optimizer check. Opt in with --integration."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Alert, Site
from app.optimization.eligibility import OPTIMIZABLE, eligibility_for_alert
from app.optimization.service import create_optimization_run
from app.services.operational.context import get_operational_context

requires_integration = pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="live optimizer scoring requires --integration and PostgreSQL",
)


@requires_integration
def test_live_congestion_alert_produces_feasible_scored_candidate():
    session = SessionLocal()
    try:
        site = session.scalar(select(Site).where(Site.active.is_(True)).order_by(Site.site_id))
        assert site is not None
        ctx = get_operational_context(session, site_code=site.code)
        from app.db.models import Shift

        stale_id = session.scalar(
            select(Shift.shift_id)
            .where(Shift.site_id == site.site_id, Shift.shift_id != ctx.shift_id)
            .order_by(Shift.shift_id.desc())
        )
        stale = get_operational_context(session, site_code=site.code, shift_id=stale_id) if stale_id else ctx
        assert stale.shift_id == ctx.shift_id
        alerts = list(session.scalars(select(Alert).where(Alert.status != "RESOLVED").order_by(Alert.alert_id.desc()).limit(80)))
        alert = next(
            (
                row
                for row in alerts
                if eligibility_for_alert(row) == OPTIMIZABLE and row.alert_type == "CONGESTION_RISK" and row.equipment_id
            ),
            None,
        )
        if alert is None:
            pytest.skip("no active CONGESTION_RISK with equipment")
        payload = create_optimization_run(session, stale, f"alert-{alert.alert_id}")
        assert payload["outcome"] == "FEASIBLE"
        scored = [row for row in (payload.get("candidates") or []) if row.get("score") is not None]
        assert scored
        best = scored[0]
        assert best.get("loaderCode")
        assert best.get("travelMinutes") is not None
        assert best.get("waitMinutes") is not None
        assert best.get("score") is not None
        assert best.get("destZoneCode")
    finally:
        session.close()

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import Ctx, DbSession
from app.services.operational.context import parse_poste_name, resolve_shifts
from app.services.operational.production import production_for_shifts, production_summary

router = APIRouter()


@router.get("")
def production(
    session: DbSession,
    ctx: Ctx,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    poste: str | None = Query(None),
):
    if from_date is None and to_date is None and not poste:
        return production_summary(session, ctx)
    from_date = from_date or ctx.sim_now.date()
    to_date = to_date or from_date
    poste_name = parse_poste_name(poste)
    shifts = resolve_shifts(session, ctx.site_id, from_date, to_date, poste_name)
    return production_for_shifts(session, shifts)


@router.get("/actuals")
def actuals(session: DbSession, ctx: Ctx):
    from sqlalchemy import select

    from app.db.models import ProductionActual

    if ctx.shift_id is not None:
        rows = session.scalars(
            select(ProductionActual)
            .where(ProductionActual.shift_id == ctx.shift_id)
            .order_by(ProductionActual.ts.desc())
            .limit(200)
        ).all()
    else:
        rows = session.scalars(
            select(ProductionActual).order_by(ProductionActual.ts.desc()).limit(200)
        ).all()
    return [
        {
            "id": r.production_id,
            "ts": r.ts.isoformat(),
            "tonnes": float(r.tonnes or 0),
            "cycles": r.cycles or 0,
        }
        for r in rows
    ]

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.services.operational.production import production_summary

router = APIRouter()


@router.get("")
def production(session: DbSession, ctx: Ctx):
    return production_summary(session, ctx)


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

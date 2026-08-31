"""Read-only external context API. Canonical weather only; never raw provider payloads."""

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Ctx, DbSession
from app.services.external_context.weather import get_weather_context

router = APIRouter()


@router.get("/weather")
def read_weather(session: DbSession, ctx: Ctx, site_id: int | None = Query(default=None, gt=0)):
    if site_id is not None and site_id != ctx.site_id:
        raise HTTPException(status_code=404, detail="Site not found")
    return get_weather_context(session, ctx.site_id).model_dump(mode="json")

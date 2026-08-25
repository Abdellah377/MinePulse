"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.operational.context import OperationalContext, get_operational_context
from app.services.operational.ids import parse_shift_id

DbSession = Annotated[Session, Depends(get_db)]


def operational_context(
    db: DbSession,
    site_code: str | None = Query(None, alias="site_code"),
    shift_id: str | None = Query(None, alias="shift_id"),
) -> OperationalContext:
    return get_operational_context(db, site_code=site_code, shift_id=parse_shift_id(shift_id))


Ctx = Annotated[OperationalContext, Depends(operational_context)]

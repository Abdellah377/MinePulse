from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.settings import OperationalSettingsPatch
from app.services.operational.settings import get_operational_settings, patch_operational_settings

router = APIRouter()


@router.get("/operational")
def get_settings(session: DbSession):
    return get_operational_settings(session)


@router.patch("/operational")
def patch_settings(body: OperationalSettingsPatch, session: DbSession):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return patch_operational_settings(session, updates)

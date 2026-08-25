from pydantic import BaseModel, Field


class ZonePoint(BaseModel):
    x: float
    y: float


class ZoneCreateRequest(BaseModel):
    code: str
    name: str
    type: str = "restreinte"
    points: list[ZonePoint]
    color: str | None = None
    description: str | None = None
    capacity: int | None = None


class ZonePatchRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    points: list[ZonePoint] | None = None
    color: str | None = None
    description: str | None = None
    capacity: int | None = None

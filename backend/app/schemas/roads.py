from pydantic import BaseModel, Field


class RoadPoint(BaseModel):
    x: float
    y: float


class RoadCreateRequest(BaseModel):
    code: str
    name: str
    fromZoneId: str | None = None
    toZoneId: str | None = None
    points: list[RoadPoint]
    distanceKm: float | None = None
    speedLimitKmh: float | None = None
    description: str | None = None
    status: str | None = "OPEN"
    statusReason: str | None = None
    statusNote: str | None = None


class RoadPatchRequest(BaseModel):
    name: str | None = None
    fromZoneId: str | None = None
    toZoneId: str | None = None
    points: list[RoadPoint] | None = None
    distanceKm: float | None = None
    speedLimitKmh: float | None = Field(default=None)
    description: str | None = None
    status: str | None = None
    statusReason: str | None = None
    statusNote: str | None = None

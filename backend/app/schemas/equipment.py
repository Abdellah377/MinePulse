"""Equipment live DTO schemas (API contract)."""

from pydantic import BaseModel, Field


class CycleStageDto(BaseModel):
    key: str
    minutes: float | None = None
    isCurrent: bool = False
    isOutlier: bool = False


class EquipmentLiveDto(BaseModel):
    id: str
    code: str
    type: str
    model: str
    state: str
    position: dict[str, float] | None = None
    heading: float | None = None
    speedKmh: float | None = None
    fuelPct: float | None = None
    gasoilLph: float | None = None
    tdPct: float | None = None
    tuPct: float | None = None
    engineOn: bool | None = None
    operatorId: str | None = None
    zoneId: str | None = None
    destinationZoneId: str | None = None
    payloadTons: float | None = None
    capacityTons: float | None = None
    odometerKm: float | None = None
    engineHours: float | None = None
    tripsThisShift: int = 0
    waitingMinutesThisShift: float = 0
    idleMinutesThisShift: float = 0
    lastUpdate: int | None = None
    siteId: str
    healthScore: float | None = None
    cycleActuel: list[CycleStageDto] = Field(default_factory=list)
    cycleDureeMoyenneMin: float | None = None

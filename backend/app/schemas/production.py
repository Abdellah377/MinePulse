"""Production summary DTO schemas."""

from pydantic import BaseModel


class ProductionRecordDto(BaseModel):
    label: str
    tonnage: float
    target: float | None = None
    targetCycleMin: float | None = None


class ProductionSummaryDto(BaseModel):
    hourly: list[ProductionRecordDto]
    daily: list[ProductionRecordDto]
    shiftly: list[ProductionRecordDto]

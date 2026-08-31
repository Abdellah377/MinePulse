from app.db.models.ai import (
    AiInvestigation,
    AiRecommendation,
    AiRecommendationDecision,
    AiRecommendationDiscussionMessage,
    Prediction,
)
from app.db.models.equipment import Equipment, Material, Operator
from app.db.models.events import Alert, DowntimeEvent, FuelEvent, MaintenanceEvent, SystemEvent
from app.db.models.operations import (
    Cycle,
    CycleStage,
    EquipmentAssignment,
    HaulRoad,
    Trip,
    Zone,
)
from app.db.models.production import ProductionActual, ProductionTarget
from app.db.models.site import Shift, Site
from app.db.models.telemetry import EquipmentPosition, EquipmentState, EquipmentTelemetry
from app.db.models.operational_settings import OperationalSetting
from app.db.models.tyres import TyreTelemetry

__all__ = [
    "Site",
    "Shift",
    "Operator",
    "Material",
    "Equipment",
    "Zone",
    "HaulRoad",
    "EquipmentAssignment",
    "EquipmentPosition",
    "EquipmentTelemetry",
    "EquipmentState",
    "Cycle",
    "CycleStage",
    "Trip",
    "FuelEvent",
    "MaintenanceEvent",
    "DowntimeEvent",
    "ProductionTarget",
    "ProductionActual",
    "SystemEvent",
    "Alert",
    "Prediction",
    "AiRecommendation",
    "AiRecommendationDecision",
    "AiRecommendationDiscussionMessage",
    "AiInvestigation",
    "TyreTelemetry",
    "OperationalSetting",
]

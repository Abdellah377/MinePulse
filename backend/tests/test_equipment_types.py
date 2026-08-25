"""WATER_TRUCK / LIGHT_VEHICLE must not be reported as haul trucks."""

from app.db.enums import EquipmentType
from app.mappers.enums import EQUIPMENT_TYPE_TO_UI


def test_non_haul_types_are_not_mapped_to_haul_truck():
    assert EQUIPMENT_TYPE_TO_UI[EquipmentType.WATER_TRUCK] == "water_truck"
    assert EQUIPMENT_TYPE_TO_UI[EquipmentType.LIGHT_VEHICLE] == "light_vehicle"
    assert EQUIPMENT_TYPE_TO_UI[EquipmentType.OTHER] == "other"
    assert EQUIPMENT_TYPE_TO_UI[EquipmentType.HAUL_TRUCK] == "haul_truck"
    for etype, ui in EQUIPMENT_TYPE_TO_UI.items():
        if etype is not EquipmentType.HAUL_TRUCK:
            assert ui != "haul_truck", f"{etype} must not count as haul_truck"

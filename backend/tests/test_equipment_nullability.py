from datetime import datetime, timezone

from app.db.enums import EquipmentState, EquipmentType
from app.db.models import Equipment
from app.mappers.dto import equipment_to_dto
from app.schemas.equipment import EquipmentLiveDto


def test_equipment_live_contract_preserves_unknown_telemetry_as_null(monkeypatch):
    fixed_now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)

    import app.mappers.dto as dto

    monkeypatch.setattr(dto, "get_operational_now", lambda: fixed_now)

    eq = Equipment(
        equipment_id=101,
        site_id=2,
        code="TR-01",
        type=EquipmentType.HAUL_TRUCK,
        model="CAT 777",
        current_state=EquipmentState.UNKNOWN,
        active=True,
        metadata_={},
    )

    payload = equipment_to_dto(eq, None, None, {}, "SITE-B")
    parsed = EquipmentLiveDto(**payload)

    assert parsed.heading is None
    assert parsed.speedKmh is None
    assert parsed.engineOn is None
    assert parsed.healthScore is None

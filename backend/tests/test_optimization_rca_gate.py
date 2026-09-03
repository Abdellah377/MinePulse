from app.db.enums import EquipmentType
from app.optimization.rca_gate import rca_constraints


def test_confirmed_loader_rca_may_hard_exclude():
    result = rca_constraints(
        diagnosis_status="CONFIRMED",
        reliable_root_cause=True,
        equipment_id=22,
        equipment_type=EquipmentType.EXCAVATOR,
        supported_hypothesis_ids=["h-1"],
    )
    assert result.hard_exclude_loader_ids == {22}
    assert result.caution_notes == []


def test_confirmed_on_haul_truck_does_not_exclude_loader():
    result = rca_constraints(
        diagnosis_status="CONFIRMED",
        reliable_root_cause=True,
        equipment_id=7,
        equipment_type=EquipmentType.HAUL_TRUCK,
        supported_hypothesis_ids=["h-1"],
    )
    assert result.hard_exclude_loader_ids == set()


def test_probable_is_caution_not_hard_exclude():
    result = rca_constraints(
        diagnosis_status="PROBABLE",
        reliable_root_cause=False,
        equipment_id=22,
        equipment_type=EquipmentType.LOADER,
        supported_hypothesis_ids=["h-2"],
    )
    assert result.hard_exclude_loader_ids == set()
    assert result.caution_notes
    assert "h-2" in result.evidence_ids


def test_hypothesis_only_is_evidence():
    result = rca_constraints(
        diagnosis_status="INCONCLUSIVE",
        reliable_root_cause=False,
        equipment_id=22,
        equipment_type=EquipmentType.EXCAVATOR,
        supported_hypothesis_ids=["h-9"],
    )
    assert result.hard_exclude_loader_ids == set()
    assert result.caution_notes == []
    assert result.evidence_ids == ["h-9"]

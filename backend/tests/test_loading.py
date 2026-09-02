from types import SimpleNamespace

from app.db.enums import EquipmentType
from app.services.operational.loading import MAX_LOADERS, resolve_relevant_loader_ids


def _eq(equipment_id: int, *, eq_type=EquipmentType.EXCAVATOR, active=True):
    return SimpleNamespace(equipment_id=equipment_id, type=eq_type, active=active)


def test_explicit_loader_ids_skip_assignment_discovery():
    equipment = {10: _eq(10), 11: _eq(11), 12: _eq(12)}
    assignments = {
        1: SimpleNamespace(loader_id=10, origin_zone_id=1),
        2: SimpleNamespace(loader_id=12, origin_zone_id=1),
    }
    resolved = resolve_relevant_loader_ids(
        loader_ids=[11, 10, 11],
        equipment_by_id=equipment,
        assignments=assignments,
        equipment_id=1,
        zone_id=None,
    )
    assert resolved == [11, 10]


def test_explicit_loader_ids_omit_unknown_inactive_and_non_loaders():
    equipment = {
        10: _eq(10),
        11: _eq(11, active=False),
        12: _eq(12, eq_type=EquipmentType.HAUL_TRUCK),
    }
    resolved = resolve_relevant_loader_ids(
        loader_ids=[10, 11, 12, 99],
        equipment_by_id=equipment,
        assignments={},
        equipment_id=None,
        zone_id=None,
    )
    assert resolved == [10]


def test_explicit_loader_ids_keep_current_first_within_bound():
    equipment = {i: _eq(i) for i in range(1, MAX_LOADERS + 3)}
    requested = [1] + list(range(2, MAX_LOADERS + 3))
    resolved = resolve_relevant_loader_ids(
        loader_ids=requested,
        equipment_by_id=equipment,
        assignments={},
        equipment_id=None,
        zone_id=None,
    )
    assert resolved[0] == 1
    assert len(resolved) == MAX_LOADERS


def test_omitted_loader_ids_still_use_assignments():
    equipment = {10: _eq(10), 11: _eq(11)}
    assignments = {7: SimpleNamespace(loader_id=11, origin_zone_id=2)}
    resolved = resolve_relevant_loader_ids(
        loader_ids=None,
        equipment_by_id=equipment,
        assignments=assignments,
        equipment_id=None,
        zone_id=None,
    )
    assert resolved == [11]

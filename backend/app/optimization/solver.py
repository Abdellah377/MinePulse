"""Deterministic bounded dispatch candidates and scoring.

Reads operational services only. Never imports the simulator, road mutations,
or an LLM provider. Incomplete metrics stay null — never coerced to zero.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.db.enums import EquipmentState, EquipmentType
from app.services.operational.loading import MAX_LOADERS
from app.services.operational.road_network import MAX_CANDIDATE_PATHS, can_reach, candidate_paths

OPTIMIZER_VERSION = "1.0.0"
DEFAULT_WEIGHTS = {"w_travel": 1.0, "w_wait": 1.0}
UNAVAILABLE_STATES = frozenset(
    {
        EquipmentState.STOPPED_MECHANICAL,
        EquipmentState.MAINTENANCE,
        EquipmentState.ENGINE_OFF,
        EquipmentState.NO_DATA,
    }
)
_LOADER_TYPES = {EquipmentType.EXCAVATOR, EquipmentType.LOADER}

FEASIBLE = "FEASIBLE"
NO_FEASIBLE_PLAN = "NO_FEASIBLE_PLAN"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_APPLICABLE = "NOT_APPLICABLE"
ERROR = "ERROR"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return str(value.value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def snapshot_digest(snapshot: dict) -> str:
    payload = json.dumps(_jsonable(snapshot), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_value(equipment: Any) -> str:
    state = getattr(equipment, "current_state", None)
    return state.value if hasattr(state, "value") else str(state or "")


def _is_available(equipment: Any) -> bool:
    if equipment is None or not getattr(equipment, "active", True):
        return False
    state = getattr(equipment, "current_state", None)
    return state not in UNAVAILABLE_STATES


def _wait_for_loader(loading: dict, loader_id: int) -> float | None:
    for row in loading.get("loaders") or []:
        if row.get("loaderId") != loader_id:
            continue
        waiting = row.get("waitingTrucks") or []
        count = row.get("waitingTruckCount")
        if count == 0 or not waiting:
            return 0.0 if count == 0 else None
        minutes = [item.get("waitingMinutes") for item in waiting if item.get("waitingMinutes") is not None]
        if not minutes:
            return None
        return float(max(minutes))
    return None


def score_candidate(travel: float | None, wait: float | None, weights: dict) -> float | None:
    if travel is None or wait is None:
        return None
    w_travel = float(weights.get("w_travel", 1.0))
    w_wait = float(weights.get("w_wait", 1.0))
    return round(w_travel * travel + w_wait * wait, 3)


def _rank_key(candidate: dict) -> tuple:
    score = candidate.get("score")
    loader_id = candidate.get("loaderId") or 0
    roads = tuple(candidate.get("roadIds") or [])
    return (0 if score is not None else 1, score if score is not None else 0.0, loader_id, roads)


def candidate_loader_ids(*, assignment: Any, loaders: list[Any]) -> list[int]:
    """Available loaders the solver will consider. Current assignment first."""
    ids: list[int] = []
    current = assignment.loader_id if assignment is not None else None
    if current is not None:
        ids.append(current)
    for row in loaders:
        if not _is_available(row):
            continue
        loader_id = row.equipment_id
        if loader_id not in ids:
            ids.append(loader_id)
    return ids[:MAX_LOADERS]


def generate_candidates(
    *,
    truck: Any,
    assignment: Any,
    loaders: list[Any],
    roads: list[dict],
    zone_codes: dict[int, str],
    loading: dict,
    origin_code: str | None,
    dest_code: str | None,
    weights: dict | None = None,
    loader_zones: dict[int, str] | None = None,
) -> list[dict]:
    """Bounded generation around the subject truck. Never invents a dump destination.

    Loader origin comes only from ``loader_zones`` (fresh position or home zone).
    ``origin_code`` is the subject truck haul origin and is never used as a shovel bench.
    """
    weights = weights or dict(DEFAULT_WEIGHTS)
    dest = dest_code
    if dest is None and assignment is not None and assignment.destination_zone_id is not None:
        dest = zone_codes.get(assignment.destination_zone_id)
    if dest is None:
        return []
    _ = origin_code  # subject-truck haul origin; never a loader bench

    current_loader_id = assignment.loader_id if assignment is not None else None
    allowed_ids = set(candidate_loader_ids(assignment=assignment, loaders=loaders))
    available_loaders = [row for row in loaders if _is_available(row) and row.equipment_id in allowed_ids]
    pairs: list[tuple[Any, str]] = []
    known_zones = loader_zones or {}
    for loader in available_loaders:
        origin = known_zones.get(loader.equipment_id)
        if origin is None:
            continue
        if not can_reach(origin, dest, roads) and origin != dest:
            continue
        pairs.append((loader, origin))

    candidates: list[dict] = []
    index = 0
    for loader, origin in pairs:
        notes: list[str] = []
        if origin == dest:
            paths = [
                {
                    "roadIds": [],
                    "totalDistanceKm": 0.0,
                    "estimatedTravelMinutes": 0.0,
                    "containsRestrictedRoad": False,
                }
            ]
        else:
            paths = candidate_paths(origin, dest, roads, max_paths=MAX_CANDIDATE_PATHS)
        if not paths:
            continue
        wait = _wait_for_loader(loading, loader.equipment_id)
        seen_paths: set[tuple] = set()
        for path in paths:
            road_ids = tuple(path.get("roadIds") or [])
            fingerprint = (loader.equipment_id, origin, dest, road_ids)
            if fingerprint in seen_paths:
                continue
            seen_paths.add(fingerprint)
            travel = path.get("estimatedTravelMinutes")
            distance = path.get("totalDistanceKm")
            path_notes = list(notes)
            if path.get("containsRestrictedRoad"):
                path_notes.append("RESTRICTED")
            if travel is None:
                path_notes.append("non évalué")
            score = score_candidate(travel, wait, weights)
            index += 1
            candidates.append(
                {
                    "candidateId": f"c-{index}",
                    "truckId": truck.equipment_id if truck is not None else None,
                    "truckCode": getattr(truck, "code", None),
                    "loaderId": loader.equipment_id,
                    "loaderCode": getattr(loader, "code", None),
                    "destZoneCode": dest,
                    "originZoneCode": origin,
                    "roadIds": list(road_ids),
                    "distanceKm": distance,
                    "travelMinutes": travel,
                    "waitMinutes": wait,
                    "score": score,
                    "constraintNotes": path_notes,
                    "isCurrent": bool(current_loader_id == loader.equipment_id),
                    "rankReason": "score" if score is not None else "non évalué",
                }
            )
    candidates.sort(key=_rank_key)
    for rank, item in enumerate(candidates, start=1):
        item["rank"] = rank
    return candidates


def dispatch_outcome(
    *,
    truck: Any,
    dest: str | None,
    candidates: list[dict],
) -> tuple[str, str | None]:
    """Classify a dispatch run. Missing metrics stay missing — never coerced to zero."""
    if truck is None:
        return INSUFFICIENT_DATA, "Camion sujet inconnu"
    if dest is None:
        return INSUFFICIENT_DATA, "Destination actuelle inconnue"
    if not candidates:
        return NO_FEASIBLE_PLAN, "Aucun itinéraire faisable"
    if all(item.get("score") is None for item in candidates):
        return INSUFFICIENT_DATA, missing_metric_reason(candidates)
    return FEASIBLE, None


def missing_metric_reason(candidates: list[dict]) -> str:
    if not candidates:
        return "Destination actuelle inconnue"
    travel_all_none = all(item.get("travelMinutes") is None for item in candidates)
    wait_all_none = all(item.get("waitMinutes") is None for item in candidates)
    if travel_all_none and wait_all_none:
        return "Temps de trajet et temps d'attente chargeur indisponibles"
    if travel_all_none:
        return "Temps de trajet indisponible"
    if wait_all_none:
        return "Temps d'attente chargeur indisponible"
    return "Temps de trajet ou temps d'attente chargeur indisponible"


def explain_run(
    *,
    outcome: str,
    eligibility: str,
    candidates: list[dict],
    weights: dict,
    weather_status: str | None,
    missing_reason: str | None = None,
) -> dict:
    recommended = next((item for item in candidates if item.get("score") is not None), None)
    return {
        "eligibility": eligibility,
        "outcome": outcome,
        "optimizerVersion": OPTIMIZER_VERSION,
        "weights": weights,
        "weatherStatus": weather_status,
        "weatherScored": False,
        "recommendedCandidateId": recommended["candidateId"] if recommended else None,
        "why": _why_text(outcome, eligibility, recommended, weights, missing_reason),
        "missingReason": missing_reason,
    }


def _why_text(
    outcome: str,
    eligibility: str,
    recommended: dict | None,
    weights: dict,
    missing_reason: str | None = None,
) -> str:
    if eligibility == NOT_APPLICABLE:
        return "Optimisation de dispatch non applicable."
    if outcome == INSUFFICIENT_DATA:
        detail = missing_reason or "métrique absente ≠ 0"
        return f"Données insuffisantes pour évaluer un plan de dispatch ({detail})."
    if outcome == NO_FEASIBLE_PLAN:
        detail = missing_reason or "Aucun itinéraire faisable"
        return (
            f"{detail} sous les contraintes dures "
            "(équipement, routes CLOSED/UNKNOWN, destination actuelle)."
        )
    if outcome == ERROR:
        return "L’optimiseur n’a pas pu terminer ce calcul."
    if recommended is None:
        return "Des candidats existent mais aucun n’a pu être noté (travel et attente doivent être tous deux connus)."
    travel = recommended.get("travelMinutes")
    wait = recommended.get("waitMinutes")
    score_line = (
        f"Score = {weights.get('w_travel', 1)} × travel ({travel} min) + "
        f"{weights.get('w_wait', 1)} × attente ({wait} min). "
        "Météo affichée, non notée. Acceptation ≠ application FMS."
    )
    if recommended.get("isCurrent"):
        return "Plan actuel déjà optimal parmi les options évaluables. " + score_line
    return score_line

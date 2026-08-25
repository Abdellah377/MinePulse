"""Geographic ↔ workspace coordinate helpers (matches site-khouribga.json)."""

from __future__ import annotations

BOUNDS = {"west": -6.689, "south": 32.649, "east": -6.658, "north": 32.674}
WORKSPACE = {"minX": -20, "minY": -20, "maxX": 1020, "maxY": 620}


def lng_lat_to_workspace(lng: float, lat: float) -> dict[str, float]:
    w, b = WORKSPACE, BOUNDS
    nx = (lng - b["west"]) / (b["east"] - b["west"])
    ny = (b["north"] - lat) / (b["north"] - b["south"])
    return {
        "x": w["minX"] + nx * (w["maxX"] - w["minX"]),
        "y": w["minY"] + ny * (w["maxY"] - w["minY"]),
    }


def workspace_to_lng_lat(x: float, y: float) -> tuple[float, float]:
    w, b = WORKSPACE, BOUNDS
    nx = (x - w["minX"]) / (w["maxX"] - w["minX"])
    ny = (y - w["minY"]) / (w["maxY"] - w["minY"])
    lng = b["west"] + nx * (b["east"] - b["west"])
    lat = b["north"] - ny * (b["north"] - b["south"])
    return lng, lat

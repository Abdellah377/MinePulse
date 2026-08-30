"""Train-only median baselines for cycle-time V1."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from app.ml.cycle_time.features import FeatureRow, MISSING_CAT


def _route_token(row: FeatureRow) -> str:
    return f"{row.values.get('origin_code')}|{row.values.get('destination_code')}"


@dataclass
class MedianBaselines:
    global_median: float = 0.0
    by_route: dict[str, float] = field(default_factory=dict)
    by_truck: dict[str, float] = field(default_factory=dict)

    def fit(self, rows: list[FeatureRow]) -> "MedianBaselines":
        targets = [row.target_minutes for row in rows if row.target_minutes is not None]
        if not targets:
            raise ValueError("Cannot fit baselines: no training targets.")
        self.global_median = float(median(targets))
        route_vals: dict[str, list[float]] = defaultdict(list)
        truck_vals: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.target_minutes is None:
                continue
            route_vals[_route_token(row)].append(row.target_minutes)
            truck = row.values.get("truck_code")
            if truck and truck != MISSING_CAT:
                truck_vals[str(truck)].append(row.target_minutes)
        self.by_route = {key: float(median(vals)) for key, vals in route_vals.items()}
        self.by_truck = {key: float(median(vals)) for key, vals in truck_vals.items()}
        return self

    def predict_global(self, rows: list[FeatureRow]) -> list[float]:
        return [self.global_median for _ in rows]

    def predict_route(self, rows: list[FeatureRow]) -> list[float]:
        return [self.by_route.get(_route_token(row), self.global_median) for row in rows]

    def predict_truck(self, rows: list[FeatureRow]) -> list[float]:
        out: list[float] = []
        for row in rows:
            truck = row.values.get("truck_code")
            if truck and truck != MISSING_CAT and truck in self.by_truck:
                out.append(self.by_truck[truck])
            else:
                out.append(self.global_median)
        return out

    def predict_truck_route_global(self, rows: list[FeatureRow]) -> list[float]:
        """Official V1 deterministic strategy: truck → route → global. Never returns 0 unless the train median is 0."""
        out: list[float] = []
        for row in rows:
            truck = row.values.get("truck_code")
            if truck and truck != MISSING_CAT and truck in self.by_truck:
                out.append(self.by_truck[truck])
                continue
            route = _route_token(row)
            if route in self.by_route:
                out.append(self.by_route[route])
                continue
            out.append(self.global_median)
        return out

    def predict(self, name: str, rows: list[FeatureRow]) -> list[float]:
        if name == "global":
            return self.predict_global(rows)
        if name == "route":
            return self.predict_route(rows)
        if name == "truck":
            return self.predict_truck(rows)
        if name == "truck_route_global":
            return self.predict_truck_route_global(rows)
        raise KeyError(name)

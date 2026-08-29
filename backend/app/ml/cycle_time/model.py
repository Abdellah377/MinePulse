"""sklearn pipeline for cycle-time V1.

HistGradientBoostingRegressor with dense one-hot categoricals.
PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder

from app.ml.cycle_time.baselines import MedianBaselines
from app.ml.cycle_time.contracts import MODEL_VERSION, ModelStatus
from app.ml.cycle_time.features import CATEGORICAL_FEATURES, FEATURE_NAMES, NUMERIC_FEATURES, FeatureRow

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "cycle_time"
ARTIFACT_FILE = f"{MODEL_VERSION}.joblib"

CAT_INDEXES = list(range(len(CATEGORICAL_FEATURES)))
NUM_INDEXES = list(range(len(CATEGORICAL_FEATURES), len(FEATURE_NAMES)))


def _as_float(values):
    return np.asarray(values, dtype=np.float64)


def rows_to_matrix(rows: list[FeatureRow]) -> np.ndarray:
    matrix: list[list[Any]] = []
    for row in rows:
        cats = [row.values[name] for name in CATEGORICAL_FEATURES]
        nums: list[Any] = []
        for name in NUMERIC_FEATURES:
            value = row.values[name]
            nums.append(np.nan if value is None else float(value))
        matrix.append(cats + nums)
    return np.array(matrix, dtype=object)


def build_pipeline(
    *,
    max_depth: int = 3,
    min_samples_leaf: int = 10,
    max_iter: int = 80,
    learning_rate: float = 0.1,
    random_state: int = 42,
) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CAT_INDEXES,
            ),
            (
                "num",
                FunctionTransformer(_as_float, validate=False),
                NUM_INDEXES,
            ),
        ],
        remainder="drop",
    )
    model = HistGradientBoostingRegressor(
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        max_iter=max_iter,
        learning_rate=learning_rate,
        random_state=random_state,
        l2_regularization=0.1,
    )
    return Pipeline([("prep", preprocessor), ("hgb", model)])


GRID = (
    {"max_depth": 3, "min_samples_leaf": 10},
    {"max_depth": 3, "min_samples_leaf": 15},
    {"max_depth": 4, "min_samples_leaf": 10},
)


def predict_pipeline(pipeline: Pipeline, rows: list[FeatureRow]) -> list[float]:
    if not rows:
        return []
    preds = pipeline.predict(rows_to_matrix(rows))
    return [float(value) for value in preds]


@dataclass
class CycleTimeArtifact:
    pipeline: Pipeline | None
    baselines: MedianBaselines
    served_predictor: str
    residual_q10: float
    residual_q90: float
    feature_names: tuple[str, ...]
    model_version: str = MODEL_VERSION
    model_status: ModelStatus = ModelStatus.BASELINE_NOT_BEATEN
    metadata: dict[str, Any] = field(default_factory=dict)


def save_artifact(artifact: CycleTimeArtifact, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    return path


def load_artifact(path: Path) -> CycleTimeArtifact:
    if not path.is_file():
        raise FileNotFoundError(path)
    return joblib.load(path)

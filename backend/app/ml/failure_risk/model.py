"""sklearn pipelines for Failure-Risk V1.

Logistic regression and HistGradientBoostingClassifier. No extra GBDT libraries.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from app.ml.failure_risk.baselines import FailureRiskBaselines
from app.ml.failure_risk.contracts import MODEL_VERSION, ModelStatus
from app.ml.failure_risk.features import CATEGORICAL_FEATURES, FEATURE_NAMES, NUMERIC_FEATURES, FeatureRow

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_DIR = BACKEND_ROOT / "artifacts" / "failure_risk"
ARTIFACT_FILE = f"{MODEL_VERSION}.joblib"

CAT_INDEXES = list(range(len(CATEGORICAL_FEATURES)))
NUM_INDEXES = list(range(len(CATEGORICAL_FEATURES), len(FEATURE_NAMES)))

HGB_DEFAULT_PARAMS: dict[str, Any] = {
    "max_depth": 3,
    "min_samples_leaf": 10,
    "max_iter": 80,
    "learning_rate": 0.1,
    "l2_regularization": 0.1,
    "max_bins": 255,
}
HGB_GRID = (
    {"max_depth": 3, "min_samples_leaf": 10},
    {"max_depth": 3, "min_samples_leaf": 15},
    {"max_depth": 4, "min_samples_leaf": 10},
)
HGB_LIMITED_TUNE = (
    dict(HGB_DEFAULT_PARAMS),
    {
        **HGB_DEFAULT_PARAMS,
        "learning_rate": 0.05,
        "max_iter": 120,
        "min_samples_leaf": 15,
    },
    {
        **HGB_DEFAULT_PARAMS,
        "max_depth": 4,
        "min_samples_leaf": 20,
        "l2_regularization": 0.5,
    },
    {
        **HGB_DEFAULT_PARAMS,
        "learning_rate": 0.08,
        "max_iter": 100,
        "max_leaf_nodes": 15,
    },
)


def schema_indexes(feature_names: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...], list[int], list[int]]:
    cats = tuple(name for name in feature_names if name in CATEGORICAL_FEATURES)
    nums = tuple(name for name in feature_names if name not in CATEGORICAL_FEATURES)
    return cats, nums, list(range(len(cats))), list(range(len(cats), len(feature_names)))


def _as_float(values):
    return np.asarray(values, dtype=np.float64)


def rows_to_matrix(
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> np.ndarray:
    cats, nums, _cat_idx, _num_idx = schema_indexes(feature_names)
    matrix: list[list[Any]] = []
    for row in rows:
        cat_values = [row.values.get(name) for name in cats]
        num_values: list[Any] = []
        for name in nums:
            value = row.values.get(name)
            num_values.append(np.nan if value is None else float(value))
        matrix.append(cat_values + num_values)
    return np.array(matrix, dtype=object)


def _preprocessor(*, scale: bool, feature_names: tuple[str, ...] = FEATURE_NAMES) -> ColumnTransformer:
    _cats, _nums, cat_indexes, num_indexes = schema_indexes(feature_names)
    numeric_steps: list[tuple[str, Any]] = [
        ("as_float", FunctionTransformer(_as_float, validate=False)),
        ("impute", SimpleImputer(strategy="median")),
    ]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))
    return ColumnTransformer(
        transformers=[
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                cat_indexes,
            ),
            ("num", Pipeline(numeric_steps), num_indexes),
        ],
        remainder="drop",
    )


def build_logistic_pipeline(
    *,
    random_state: int = 42,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> Pipeline:
    return Pipeline(
        [
            ("prep", _preprocessor(scale=True, feature_names=feature_names)),
            (
                "clf",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=500,
                    solver="lbfgs",
                    random_state=random_state,
                ),
            ),
        ]
    )


def build_hgb_pipeline(
    *,
    max_depth: int | None = 3,
    min_samples_leaf: int = 10,
    max_iter: int = 80,
    learning_rate: float = 0.1,
    random_state: int = 42,
    l2_regularization: float = 0.1,
    max_bins: int = 255,
    max_leaf_nodes: int | None = 31,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> Pipeline:
    return Pipeline(
        [
            ("prep", _preprocessor(scale=False, feature_names=feature_names)),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_depth=max_depth,
                    min_samples_leaf=min_samples_leaf,
                    max_iter=max_iter,
                    learning_rate=learning_rate,
                    random_state=random_state,
                    class_weight="balanced",
                    l2_regularization=l2_regularization,
                    max_bins=max_bins,
                    max_leaf_nodes=max_leaf_nodes,
                ),
            ),
        ]
    )


def _positive_index(pipeline: Pipeline) -> int:
    classes = list(pipeline.classes_)
    if 1 in classes:
        return classes.index(1)
    return len(classes) - 1


def predict_proba_positive(
    pipeline: Pipeline,
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[float]:
    if not rows:
        return []
    proba = pipeline.predict_proba(rows_to_matrix(rows, feature_names=feature_names))
    idx = _positive_index(pipeline)
    return [float(row[idx]) for row in proba]


def transformed_feature_names(
    pipeline: Pipeline,
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[str]:
    prep = pipeline.named_steps["prep"]
    cat = prep.named_transformers_["cat"]
    cats, nums, _cat_idx, _num_idx = schema_indexes(feature_names)
    cat_names = [str(name) for name in cat.get_feature_names_out(list(cats))]
    return cat_names + list(nums)


def feature_importance(
    pipeline: Pipeline,
    kind: str,
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[tuple[str, float]]:
    names = transformed_feature_names(pipeline, feature_names=feature_names)
    clf = pipeline.named_steps["clf"]
    if kind == "logistic":
        coef = np.asarray(clf.coef_).ravel()
        pairs = list(zip(names, (float(v) for v in coef)))
        pairs.sort(key=lambda item: abs(item[1]), reverse=True)
        return pairs
    importances = getattr(clf, "feature_importances_", None)
    if importances is None:
        return []
    pairs = list(zip(names, (float(v) for v in np.asarray(importances).ravel())))
    pairs.sort(key=lambda item: item[1], reverse=True)
    return pairs


@dataclass
class FailureRiskArtifact:
    logistic: Pipeline | None
    hgb: Pipeline | None
    baselines: FailureRiskBaselines
    served_predictor: str
    threshold: float
    feature_names: tuple[str, ...]
    model_version: str = MODEL_VERSION
    model_status: ModelStatus = ModelStatus.BASELINE_NOT_BEATEN
    top_signals: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def save_artifact(artifact: FailureRiskArtifact, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    return path


def load_artifact(path: Path) -> FailureRiskArtifact:
    if not path.is_file():
        raise FileNotFoundError(path)
    return joblib.load(path)

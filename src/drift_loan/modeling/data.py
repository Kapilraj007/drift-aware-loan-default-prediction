"""Read and validate the shared Sprint 1 feature-store contract for modeling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from drift_loan.data import (
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    SPLIT_COLUMN,
    TARGET_COLUMN,
    read_feature_store,
)

from .errors import ModelingDataError

REQUIRED_SPLITS: tuple[str, ...] = ("train", "validation", "shift")
METADATA_COLUMNS: tuple[str, ...] = (
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    SPLIT_COLUMN,
    TARGET_COLUMN,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ModelingDataset:
    """Validated scaled and unscaled feature-store views for model training."""

    root: Path
    feature_names: tuple[str, ...]
    unscaled: pd.DataFrame
    scaled: pd.DataFrame
    manifest: Mapping[str, Any]
    manifest_sha256: str

    def split_frame(self, split_name: str, *, feature_view: str) -> pd.DataFrame:
        """Return one chronological temporal split with its metadata intact."""

        if split_name not in REQUIRED_SPLITS:
            raise ModelingDataError(
                f"split_name must be one of {REQUIRED_SPLITS}; got {split_name!r}."
            )
        if feature_view == "unscaled":
            source = self.unscaled
        elif feature_view == "scaled":
            source = self.scaled
        else:
            raise ModelingDataError("feature_view must be 'unscaled' or 'scaled'.")
        frame = source.loc[source[SPLIT_COLUMN].astype(str) == split_name].copy()
        if frame.empty:
            raise ModelingDataError(f"Feature store has no rows in the {split_name!r} split.")
        return frame.sort_values(ISSUE_DATE_COLUMN, kind="stable").reset_index(drop=True)


def _load_manifest(root: Path) -> tuple[dict[str, Any], str]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ModelingDataError(f"Feature-store manifest is missing: {manifest_path}")
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelingDataError(
            f"Feature-store manifest contains invalid JSON: {manifest_path}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ModelingDataError("Feature-store manifest must contain a JSON object.")
    return loaded, _sha256_file(manifest_path)


def _feature_names(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    raw_names = manifest.get("feature_names")
    if not isinstance(raw_names, list) or not raw_names or not all(
        isinstance(name, str) and name for name in raw_names
    ):
        raise ModelingDataError(
            "Feature-store manifest must contain a non-empty feature_names list."
        )
    names = tuple(raw_names)
    if len(set(names)) != len(names):
        raise ModelingDataError("Feature-store manifest feature_names must be unique.")
    forbidden = sorted(set(names).intersection(METADATA_COLUMNS))
    if forbidden:
        raise ModelingDataError(
            f"Feature-store manifest treats metadata as model features: {forbidden}."
        )
    return names


def _validate_view(
    frame: pd.DataFrame,
    *,
    feature_names: tuple[str, ...],
    view_name: str,
) -> None:
    required = [*METADATA_COLUMNS, *feature_names]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ModelingDataError(f"{view_name} feature view is missing required columns: {missing}")
    if not frame.columns.is_unique:
        raise ModelingDataError(f"{view_name} feature view contains duplicate column names.")
    if frame.empty:
        raise ModelingDataError(f"{view_name} feature view is empty.")

    target = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    target_values = target.to_numpy(dtype=np.float64)
    valid_target_values = (
        not target.isna().any()
        and np.isfinite(target_values).all()
        and np.isin(target_values, (0.0, 1.0)).all()
    )
    if not valid_target_values:
        raise ModelingDataError(f"{view_name} target column must contain only binary 0/1 values.")
    dates = pd.to_datetime(frame[ISSUE_DATE_COLUMN], errors="coerce", utc=True)
    if dates.isna().any():
        raise ModelingDataError(f"{view_name} contains missing or invalid issue dates.")
    observed_splits = set(frame[SPLIT_COLUMN].astype(str).unique().tolist())
    missing_splits = sorted(set(REQUIRED_SPLITS) - observed_splits)
    if missing_splits:
        raise ModelingDataError(
            f"{view_name} is missing required temporal splits: {missing_splits}"
        )
    values = frame.loc[:, feature_names].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ModelingDataError(f"{view_name} model features contain missing or non-finite values.")


def _validate_temporal_order(frame: pd.DataFrame) -> None:
    boundaries: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for split_name in REQUIRED_SPLITS:
        subset = frame.loc[frame[SPLIT_COLUMN].astype(str) == split_name, ISSUE_DATE_COLUMN]
        dates = pd.to_datetime(subset, errors="raise", utc=True)
        boundaries[split_name] = (dates.min(), dates.max())
    if not (
        boundaries["train"][1] < boundaries["validation"][0]
        and boundaries["validation"][1] < boundaries["shift"][0]
    ):
        raise ModelingDataError(
            "Feature-store temporal splits overlap or are not strictly chronological."
        )


def load_modeling_dataset(feature_store: str | Path) -> ModelingDataset:
    """Load both feature-store views and prove their shared row/schema contract."""

    root = Path(feature_store).expanduser().resolve()
    if not root.is_dir():
        raise ModelingDataError(f"Feature-store directory does not exist: {root}")
    manifest, manifest_sha256 = _load_manifest(root)
    feature_names = _feature_names(manifest)
    try:
        unscaled = read_feature_store(root, variant="unscaled")
        scaled = read_feature_store(root, variant="scaled")
    except Exception as exc:
        raise ModelingDataError(f"Unable to read feature-store views from {root}: {exc}") from exc

    _validate_view(unscaled, feature_names=feature_names, view_name="unscaled")
    _validate_view(scaled, feature_names=feature_names, view_name="scaled")
    for column in METADATA_COLUMNS:
        try:
            assert_frame_equal(
                unscaled.loc[:, [column]].reset_index(drop=True),
                scaled.loc[:, [column]].reset_index(drop=True),
                check_dtype=False,
            )
        except AssertionError as exc:
            raise ModelingDataError(
                f"Scaled and unscaled views disagree on metadata column {column!r}."
            ) from exc
    _validate_temporal_order(unscaled)
    return ModelingDataset(
        root=root,
        feature_names=feature_names,
        unscaled=unscaled,
        scaled=scaled,
        manifest=MappingProxyType(manifest),
        manifest_sha256=manifest_sha256,
    )

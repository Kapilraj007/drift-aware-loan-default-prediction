"""Deterministic quarter-partitioned Parquet feature store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .data_dictionary import DATA_DICTIONARY_COLUMNS
from .exceptions import FeatureStoreError
from .schema import (
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    SCHEMA_VERSION,
    SPLIT_COLUMN,
    TARGET_COLUMN,
)
from .transform import LoanFeatureTransformer, TransformedFeatures

_VARIANTS = ("unscaled", "scaled")


def _sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FeatureStoreWriteResult:
    """Paths and manifest returned after a successful atomic store write."""

    root: Path
    manifest_path: Path
    artifact_directory: Path
    data_dictionary_path: Path | None
    manifest: dict[str, object]


def _json_safe(value: object) -> object:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _dataset_frame(
    dataset: TransformedFeatures,
    *,
    split_name: str,
    scaled: bool,
) -> pd.DataFrame:
    if dataset.target is None:
        raise FeatureStoreError(
            f"Feature-store dataset {split_name!r} has no target labels."
        )
    if len(dataset) == 0:
        raise FeatureStoreError(f"Feature-store dataset {split_name!r} is empty.")

    target = pd.to_numeric(dataset.target, errors="raise").astype("int8")
    invalid_targets = sorted(set(target.unique().tolist()) - {0, 1})
    if invalid_targets:
        raise FeatureStoreError(
            f"Feature-store dataset {split_name!r} has non-binary targets: {invalid_targets}"
        )

    model_features = dataset.scaled_features if scaled else dataset.features
    metadata = pd.DataFrame(
        {
            ISSUE_DATE_COLUMN: pd.to_datetime(dataset.issue_dates, errors="raise"),
            ISSUE_QUARTER_COLUMN: dataset.issue_quarters.astype("string"),
            SPLIT_COLUMN: split_name,
            TARGET_COLUMN: target,
        }
    )
    frame = pd.concat(
        [metadata.reset_index(drop=True), model_features.reset_index(drop=True)],
        axis=1,
    )
    if frame.isna().any().any():
        missing_columns = frame.columns[frame.isna().any()].tolist()
        raise FeatureStoreError(
            f"Transformed {split_name!r} data still contains missing values: {missing_columns}"
        )

    derived_quarters = frame[ISSUE_DATE_COLUMN].dt.to_period("Q").astype(str)
    mismatch = derived_quarters != frame[ISSUE_QUARTER_COLUMN].astype(str)
    if bool(mismatch.any()):
        raise FeatureStoreError(
            f"{ISSUE_QUARTER_COLUMN!r} does not match {ISSUE_DATE_COLUMN!r} in "
            f"{split_name!r}."
        )
    return frame.sort_values(ISSUE_DATE_COLUMN, kind="stable").reset_index(drop=True)


def _write_variant(
    frame: pd.DataFrame,
    *,
    root: Path,
    variant: str,
    parquet_engine: str,
) -> list[str]:
    variant_root = root / variant
    variant_root.mkdir(parents=True, exist_ok=False)
    partitions: list[str] = []

    for quarter, partition in frame.groupby(ISSUE_QUARTER_COLUMN, sort=True, observed=True):
        quarter_name = str(quarter)
        partition_splits = partition[SPLIT_COLUMN].unique().tolist()
        if len(partition_splits) != 1:
            raise FeatureStoreError(
                f"Issue quarter {quarter_name!r} crosses temporal splits: {partition_splits}"
            )
        partition_dir = variant_root / f"{ISSUE_QUARTER_COLUMN}={quarter_name}"
        partition_dir.mkdir(parents=True, exist_ok=False)
        output = partition_dir / "part-00000.parquet"
        try:
            # Hive partition readers reconstruct issue_quarter from the path.
            # Omitting it physically avoids a duplicate/conflicting field when
            # callers read the whole variant directory with pyarrow.dataset.
            partition.drop(columns=[ISSUE_QUARTER_COLUMN]).to_parquet(
                output,
                engine=parquet_engine,
                compression="snappy",
                index=False,
            )
        except (ImportError, OSError, ValueError, TypeError) as exc:
            raise FeatureStoreError(
                f"Failed to write Parquet partition {output}. Ensure the "
                f"{parquet_engine!r} engine is installed: {exc}"
            ) from exc
        partitions.append(quarter_name)
    return partitions


def write_partitioned_feature_store(
    datasets: Mapping[str, TransformedFeatures],
    root: str | Path,
    *,
    transformer: LoanFeatureTransformer,
    overwrite: bool = False,
    parquet_engine: str = "pyarrow",
    extra_metadata: Mapping[str, object] | None = None,
    data_dictionary: pd.DataFrame | None = None,
) -> FeatureStoreWriteResult:
    """Write unscaled/scaled features by issue quarter and persist artifacts.

    Output layout is stable and drift-harness friendly::

        root/unscaled/issue_quarter=YYYYQn/part-00000.parquet
        root/scaled/issue_quarter=YYYYQn/part-00000.parquet
        root/artifacts/{feature_transformer.joblib,feature_metadata.json}
        root/manifest.json
    """

    if not datasets:
        raise FeatureStoreError("At least one transformed dataset is required.")
    required_splits = {"train", "validation", "shift"}
    missing_splits = sorted(required_splits - set(datasets))
    if missing_splits:
        raise FeatureStoreError(f"Feature-store datasets are missing splits: {missing_splits}")
    unexpected_splits = sorted(set(datasets) - required_splits)
    if unexpected_splits:
        raise FeatureStoreError(f"Unexpected feature-store splits: {unexpected_splits}")

    destination = Path(root).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FeatureStoreError(
            f"Feature-store destination already exists: {destination}. "
            "Pass overwrite=True to replace it explicitly."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)

    try:
        unscaled_parts = [
            _dataset_frame(dataset, split_name=split_name, scaled=False)
            for split_name, dataset in sorted(datasets.items())
        ]
        scaled_parts = [
            _dataset_frame(dataset, split_name=split_name, scaled=True)
            for split_name, dataset in sorted(datasets.items())
        ]
        expected_names = tuple(datasets["train"].features.columns)
        for split_name, dataset in datasets.items():
            if tuple(dataset.features.columns) != expected_names:
                raise FeatureStoreError(
                    f"Feature schema for {split_name!r} differs from the training schema."
                )

        unscaled = pd.concat(unscaled_parts, ignore_index=True)
        scaled = pd.concat(scaled_parts, ignore_index=True)
        unscaled_partitions = _write_variant(
            unscaled, root=staging, variant="unscaled", parquet_engine=parquet_engine
        )
        scaled_partitions = _write_variant(
            scaled, root=staging, variant="scaled", parquet_engine=parquet_engine
        )
        if unscaled_partitions != scaled_partitions:
            raise FeatureStoreError("Scaled and unscaled partition layouts differ.")

        transformer.save_artifacts(staging / "artifacts")
        artifact_sha256 = {
            path.name: _sha256_file(path)
            for path in sorted((staging / "artifacts").iterdir())
            if path.is_file()
        }
        dictionary_relative_path: str | None = None
        if data_dictionary is not None:
            if data_dictionary.empty:
                raise FeatureStoreError("Run data dictionary must not be empty.")
            if tuple(data_dictionary.columns) != DATA_DICTIONARY_COLUMNS:
                raise FeatureStoreError(
                    "Run data dictionary columns must be exactly "
                    f"{list(DATA_DICTIONARY_COLUMNS)}."
                )
            dictionary_relative_path = "data_dictionary.csv"
            data_dictionary.to_csv(staging / dictionary_relative_path, index=False)
        row_counts = {
            split_name: len(dataset) for split_name, dataset in sorted(datasets.items())
        }
        quarter_to_split = {
            str(quarter): str(group[SPLIT_COLUMN].iloc[0])
            for quarter, group in unscaled.groupby(ISSUE_QUARTER_COLUMN, sort=True)
        }
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "layout_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "format": "parquet",
            "parquet_engine": parquet_engine,
            "compression": "snappy",
            "partition_column": ISSUE_QUARTER_COLUMN,
            "date_column": ISSUE_DATE_COLUMN,
            "target_column": TARGET_COLUMN,
            "split_column": SPLIT_COLUMN,
            "variants": list(_VARIANTS),
            "feature_names": list(expected_names),
            "feature_dtypes": {
                name: str(unscaled[name].dtype) for name in expected_names
            },
            "row_counts": row_counts,
            "total_rows": int(sum(row_counts.values())),
            "partitions": unscaled_partitions,
            "minimum_issue_quarter": min(unscaled_partitions),
            "maximum_issue_quarter": max(unscaled_partitions),
            "quarter_to_split": quarter_to_split,
            "artifact_directory": "artifacts",
            "artifact_sha256": artifact_sha256,
            "data_dictionary": dictionary_relative_path,
            "data_dictionary_sha256": (
                _sha256_file(staging / dictionary_relative_path)
                if dictionary_relative_path is not None
                else None
            ),
        }
        if extra_metadata:
            manifest["pipeline_metadata"] = _json_safe(dict(extra_metadata))
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(_json_safe(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, FeatureStoreError):
            raise
        raise FeatureStoreError(f"Failed to build feature store {destination}: {exc}") from exc

    return FeatureStoreWriteResult(
        root=destination,
        manifest_path=destination / "manifest.json",
        artifact_directory=destination / "artifacts",
        data_dictionary_path=(
            destination / "data_dictionary.csv" if data_dictionary is not None else None
        ),
        manifest=manifest,
    )


def read_feature_store(
    root: str | Path,
    *,
    variant: str = "unscaled",
    columns: list[str] | None = None,
    parquet_engine: str = "pyarrow",
) -> pd.DataFrame:
    """Read a feature-store variant from its deterministic partitions."""

    if variant not in _VARIANTS:
        raise FeatureStoreError(f"variant must be one of {_VARIANTS}; got {variant!r}.")
    variant_root = Path(root).expanduser().resolve() / variant
    files = sorted(variant_root.glob(f"{ISSUE_QUARTER_COLUMN}=*/part-*.parquet"))
    if not files:
        raise FeatureStoreError(f"No Parquet partitions found under {variant_root}.")

    frames: list[pd.DataFrame] = []
    for path in files:
        requested_physical_columns = columns
        wants_partition_column = columns is None or ISSUE_QUARTER_COLUMN in columns
        if columns is not None and ISSUE_QUARTER_COLUMN in columns:
            requested_physical_columns = [
                column for column in columns if column != ISSUE_QUARTER_COLUMN
            ]
        try:
            frame = pd.read_parquet(
                path,
                columns=requested_physical_columns,
                engine=parquet_engine,
            )
        except (ImportError, OSError, ValueError, TypeError) as exc:
            raise FeatureStoreError(f"Failed to read Parquet partition {path}: {exc}") from exc
        if wants_partition_column:
            prefix = f"{ISSUE_QUARTER_COLUMN}="
            if not path.parent.name.startswith(prefix):
                raise FeatureStoreError(f"Malformed feature-store partition path: {path.parent}")
            quarter = path.parent.name[len(prefix) :]
            insert_at = 1 if ISSUE_DATE_COLUMN in frame.columns else 0
            frame.insert(insert_at, ISSUE_QUARTER_COLUMN, quarter)
            if columns is not None:
                frame = frame.loc[:, columns]
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    sort_columns = [column for column in (ISSUE_DATE_COLUMN, SPLIT_COLUMN) if column in combined]
    if sort_columns:
        combined = combined.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    return combined

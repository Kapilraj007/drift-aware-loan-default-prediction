"""Disk-backed feature-store construction for full LendingClub exports.

The public ingestion helper intentionally returns a DataFrame and therefore
cannot bound end-to-end memory use.  This module is the production build path:
it spools resolved rows into small, chronologically addressed Parquet parts,
fits preprocessing state with repeatable chunk passes, and appends final
quarter files through :class:`pyarrow.parquet.ParquetWriter`.
"""

from __future__ import annotations

import csv
import gc
import gzip
import json
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.preprocessing import StandardScaler

from .data_dictionary import (
    DATA_DICTIONARY_COLUMNS,
    _source_for_feature,
    _transformation_for_feature,
)
from .exceptions import FeatureStoreError, FeatureValidationError, SchemaValidationError
from .feature_store import _dataset_frame, _json_safe, _sha256_file
from .ingestion import IngestionMetadata
from .schema import (
    EARLIEST_CREDIT_COLUMN,
    INGESTION_ALLOWLIST,
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    LEAKAGE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    ONE_HOT_COLUMNS,
    REQUIRED_TRAINING_COLUMNS,
    RESOLVED_STATUSES,
    SCHEMA_VERSION,
    SPLIT_COLUMN,
    TARGET_COLUMN,
    TARGET_SOURCE_COLUMN,
    missing_flag_name,
)
from .splits import TemporalSplitMetadata, _allocate_quarters, _validate_fractions
from .transform import (
    LoanFeatureTransformer,
    _one_hot_encoder,
    parse_lendingclub_dates,
)

_HEADER_SCAN_LIMIT = 100
_DEFAULT_CHUNK_SIZE = 100_000
_NA_VALUES = ("", " ", "NA", "N/A", "n/a", "null", "NULL", "None")
_MISSING_TEXT_VALUES = frozenset({"", "na", "n/a", "none", "null", "nan", "nat"})
_WORK_DIRECTORY = "_streaming_work"


@dataclass(frozen=True)
class StreamingBuildResult:
    """Internal result used to construct the stable public pipeline result."""

    root: Path
    manifest_path: Path
    artifact_directory: Path
    data_dictionary_path: Path
    ingestion: IngestionMetadata
    temporal_split: TemporalSplitMetadata
    feature_names: tuple[str, ...]


@dataclass
class _SpoolResult:
    ingestion: IngestionMetadata
    quarters: tuple[str, ...]
    quarter_rows: dict[str, int]
    dropped_unresolved_rows: int
    status_counts: dict[str, int]
    raw_missing_counts: dict[str, int]
    resolved_rows: int


class _ParquetAppender:
    """Append pandas frames as row groups while keeping one final file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._writer: pq.ParquetWriter | None = None

    def append(self, frame: pd.DataFrame) -> None:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self._writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=False)
            self._writer = pq.ParquetWriter(
                self.path,
                table.schema,
                compression="snappy",
            )
        elif not table.schema.equals(self._writer.schema, check_metadata=False):
            try:
                table = table.cast(self._writer.schema)
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
                raise FeatureStoreError(
                    f"Parquet schema changed while appending {self.path}: {exc}"
                ) from exc
        self._writer.write_table(table)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None


def _normalise_sources(
    sources: str | Path | Sequence[str | Path],
) -> tuple[Path, ...]:
    candidates: Sequence[str | Path]
    if isinstance(sources, str | Path):
        candidates = (sources,)
    else:
        candidates = sources
    paths = tuple(
        sorted(
            (Path(source).expanduser().resolve() for source in candidates),
            key=lambda path: str(path).casefold(),
        )
    )
    if not paths:
        raise SchemaValidationError("At least one LendingClub CSV source is required.")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SchemaValidationError(f"CSV source file(s) not found: {missing}")
    duplicates = sorted({str(path) for path in paths if paths.count(path) > 1})
    if duplicates:
        raise SchemaValidationError(f"Duplicate CSV source file(s): {duplicates}")
    return paths


def _open_text(path: Path) -> IO[str]:
    if path.suffix.casefold() in {".gz", ".gzip"}:
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")


def _find_header(path: Path) -> tuple[int, tuple[str, ...]]:
    with _open_text(path) as handle:
        for line_number, line in enumerate(handle):
            if line_number >= _HEADER_SCAN_LIMIT:
                break
            try:
                fields = next(csv.reader([line]))
            except csv.Error:
                continue
            stripped = tuple(field.strip() for field in fields)
            if REQUIRED_TRAINING_COLUMNS.issubset(stripped):
                if len(stripped) != len(set(stripped)):
                    duplicates = sorted(
                        {column for column in stripped if stripped.count(column) > 1}
                    )
                    raise SchemaValidationError(
                        f"Duplicate canonical column names in {path}: {duplicates}"
                    )
                return line_number, stripped
    required = ", ".join(sorted(REQUIRED_TRAINING_COLUMNS))
    raise SchemaValidationError(
        f"Could not locate a LendingClub header in {path} within the first "
        f"{_HEADER_SCAN_LIMIT} lines. Required columns: {required}."
    )


def _raw_missing_mask(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().str.casefold()
    return values.isna() | text.isin(_MISSING_TEXT_VALUES)


def _raw_part_paths(raw_root: Path, quarters: Sequence[str]) -> Iterator[Path]:
    for quarter in quarters:
        quarter_root = raw_root / f"{ISSUE_QUARTER_COLUMN}={quarter}"
        for month_root in sorted(quarter_root.glob("issue_month=*")):
            yield from sorted(month_root.glob("part-*.parquet"))


def _spool_resolved_rows(
    sources: tuple[Path, ...],
    raw_root: Path,
    *,
    chunk_size: int,
    requested_chunk_size: int | None,
) -> _SpoolResult:
    rows_read = 0
    resolved_rows = 0
    dropped_unresolved = 0
    status_counter: Counter[str] = Counter()
    quarter_counter: Counter[str] = Counter()
    raw_missing_counter: Counter[str] = Counter()
    ignored_leakage: set[str] = set()
    skipped_headers: list[tuple[str, int]] = []
    columns_loaded: tuple[str, ...] | None = None

    for source_number, path in enumerate(sources):
        header_line, header = _find_header(path)
        skipped_headers.append((str(path), header_line))
        ignored_leakage.update(set(header) & LEAKAGE_COLUMNS)
        try:
            reader = pd.read_csv(
                path,
                skiprows=header_line,
                usecols=lambda column: str(column).strip() in INGESTION_ALLOWLIST,
                na_values=_NA_VALUES,
                keep_default_na=True,
                low_memory=False,
                encoding="utf-8-sig",
                on_bad_lines="error",
                chunksize=chunk_size,
                compression="infer",
            )
            for chunk_number, chunk in enumerate(reader):
                chunk = chunk.rename(columns=lambda column: str(column).strip())
                if chunk.columns.duplicated().any():
                    duplicates = chunk.columns[chunk.columns.duplicated()].tolist()
                    raise SchemaValidationError(
                        f"Duplicate canonical column names in {path}: {duplicates}"
                    )
                missing = sorted(REQUIRED_TRAINING_COLUMNS - set(chunk.columns))
                if missing:
                    raise SchemaValidationError(
                        f"LendingClub CSV {path} is missing columns: {missing}"
                    )
                selected = tuple(
                    sorted(column for column in chunk if column in INGESTION_ALLOWLIST)
                )
                if columns_loaded is None:
                    columns_loaded = selected
                elif selected != columns_loaded:
                    raise SchemaValidationError(
                        f"Allowlisted column schema differs across sources: {path}"
                    )
                chunk = chunk.loc[:, list(selected)]
                rows_read += len(chunk)

                normalized = (
                    chunk[TARGET_SOURCE_COLUMN].astype("string").str.strip().str.casefold()
                )
                chunk_counts = normalized.fillna("<missing>").value_counts(dropna=False)
                status_counter.update(
                    {str(status): int(count) for status, count in chunk_counts.items()}
                )
                resolved_mask = normalized.isin(RESOLVED_STATUSES)
                dropped_unresolved += int((~resolved_mask).sum())
                if not bool(resolved_mask.any()):
                    continue

                resolved = chunk.loc[resolved_mask].copy()
                parsed_dates = parse_lendingclub_dates(
                    resolved[ISSUE_DATE_COLUMN],
                    field_name=ISSUE_DATE_COLUMN,
                )
                if bool(parsed_dates.isna().any()):
                    indexes = resolved.index[parsed_dates.isna()].tolist()[:10]
                    raise FeatureValidationError(
                        f"{ISSUE_DATE_COLUMN!r} is required for every retained row; "
                        f"missing at source index values {indexes}."
                    )

                resolved_rows += len(resolved)
                for column in resolved.columns:
                    raw_missing_counter[column] += int(
                        _raw_missing_mask(resolved[column]).sum()
                    )

                quarters = parsed_dates.dt.to_period("Q").astype(str)
                months = parsed_dates.dt.strftime("%Y-%m")
                address = pd.DataFrame(
                    {"quarter": quarters, "month": months},
                    index=resolved.index,
                )
                for (quarter, month), indexes in address.groupby(
                    ["quarter", "month"],
                    sort=True,
                    observed=True,
                ).groups.items():
                    part = resolved.loc[indexes].reset_index(drop=True)
                    quarter_counter[str(quarter)] += len(part)
                    output = (
                        raw_root
                        / f"{ISSUE_QUARTER_COLUMN}={quarter}"
                        / f"issue_month={month}"
                        / f"part-{source_number:04d}-{chunk_number:08d}.parquet"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    part.to_parquet(
                        output,
                        engine="pyarrow",
                        compression="snappy",
                        index=False,
                    )
        except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as exc:
            if isinstance(exc, SchemaValidationError | FeatureValidationError):
                raise
            raise SchemaValidationError(f"Failed to read LendingClub CSV {path}: {exc}") from exc

    if rows_read == 0:
        raise SchemaValidationError("LendingClub CSV ingestion produced zero rows.")
    if resolved_rows == 0:
        observed = sorted(status_counter)[:10]
        raise FeatureValidationError(
            "No resolved loan outcomes were found. Expected loan_status in "
            f"{sorted(RESOLVED_STATUSES)}; observed {observed}."
        )
    if columns_loaded is None:  # pragma: no cover - guarded by rows_read
        raise SchemaValidationError("LendingClub CSV ingestion produced no schema.")

    metadata = IngestionMetadata(
        source_files=tuple(str(path) for path in sources),
        source_bytes=tuple((str(path), path.stat().st_size) for path in sources),
        source_sha256=tuple((str(path), _sha256_file(path)) for path in sources),
        rows_read=rows_read,
        columns_loaded=columns_loaded,
        ignored_leakage_columns=tuple(sorted(ignored_leakage)),
        header_rows_skipped=tuple(skipped_headers),
        chunk_size=requested_chunk_size,
    )
    return _SpoolResult(
        ingestion=metadata,
        quarters=tuple(sorted(quarter_counter)),
        quarter_rows=dict(sorted(quarter_counter.items())),
        dropped_unresolved_rows=dropped_unresolved,
        status_counts=dict(sorted(status_counter.items())),
        raw_missing_counts=dict(raw_missing_counter),
        resolved_rows=resolved_rows,
    )


def _temporal_metadata(
    spool: _SpoolResult,
    *,
    train_fraction: float,
    validation_fraction: float,
    shift_fraction: float | None,
) -> TemporalSplitMetadata:
    resolved_shift = _validate_fractions(
        train_fraction,
        validation_fraction,
        shift_fraction,
    )
    train_count, validation_count = _allocate_quarters(
        len(spool.quarters),
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )
    train_quarters = spool.quarters[:train_count]
    validation_quarters = spool.quarters[train_count : train_count + validation_count]
    shift_quarters = spool.quarters[train_count + validation_count :]

    def count_rows(quarters: Sequence[str]) -> int:
        return int(sum(spool.quarter_rows[quarter] for quarter in quarters))

    return TemporalSplitMetadata(
        train_fraction=float(train_fraction),
        validation_fraction=float(validation_fraction),
        shift_fraction=float(resolved_shift),
        train_quarters=train_quarters,
        validation_quarters=validation_quarters,
        shift_quarters=shift_quarters,
        row_counts={
            "train": count_rows(train_quarters),
            "validation": count_rows(validation_quarters),
            "shift": count_rows(shift_quarters),
        },
        dropped_unresolved_rows=spool.dropped_unresolved_rows,
    )


def _exact_median_from_parts(
    numeric_parts: Sequence[Path],
    column: str,
    work_root: Path,
) -> float:
    non_missing = 0
    for path in numeric_parts:
        values = pd.read_parquet(path, columns=[column])[column]
        non_missing += int(values.notna().sum())
    if non_missing == 0:
        raise FeatureValidationError(
            "Cannot fit median imputation because this training feature is entirely "
            f"missing: {column}."
        )

    mmap_path = work_root / f"median-{column}.float64"
    mapped = np.memmap(mmap_path, dtype="float64", mode="w+", shape=(non_missing,))
    offset = 0
    try:
        for path in numeric_parts:
            values = pd.read_parquet(path, columns=[column])[column]
            array = values.dropna().to_numpy(dtype=np.float64, copy=False)
            mapped[offset : offset + len(array)] = array
            offset += len(array)
        if offset != non_missing:  # pragma: no cover - defensive invariant
            raise FeatureStoreError(
                f"Median spool count changed for {column}: expected {non_missing}, got {offset}."
            )
        if non_missing % 2:
            middle = non_missing // 2
            mapped.partition(middle)
            return float(mapped[middle])
        lower = non_missing // 2 - 1
        upper = non_missing // 2
        mapped.partition((lower, upper))
        return float((mapped[lower] + mapped[upper]) / 2.0)
    finally:
        mapped.flush()
        del mapped
        mmap_path.unlink(missing_ok=True)


def _fit_transformer_streaming(
    raw_root: Path,
    train_quarters: Sequence[str],
    work_root: Path,
) -> LoanFeatureTransformer:
    transformer = LoanFeatureTransformer()
    numeric_root = work_root / "numeric"
    numeric_root.mkdir(parents=True, exist_ok=False)
    numeric_parts: list[Path] = []
    categories: dict[str, set[str]] = {column: set() for column in ONE_HOT_COLUMNS}

    for part_number, raw_path in enumerate(_raw_part_paths(raw_root, train_quarters)):
        raw = pd.read_parquet(raw_path)
        prepared = transformer._prepare(raw, include_target=False)
        numeric_path = numeric_root / f"part-{part_number:08d}.parquet"
        prepared.numeric.to_parquet(
            numeric_path,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        numeric_parts.append(numeric_path)
        for column in ONE_HOT_COLUMNS:
            categories[column].update(
                str(value) for value in prepared.categoricals[column].unique()
            )
        del raw, prepared

    if not numeric_parts:  # pragma: no cover - temporal metadata guarantees rows
        raise FeatureValidationError("The temporal training window contains no rows.")

    medians = {
        column: _exact_median_from_parts(numeric_parts, column, work_root)
        for column in NUMERIC_FEATURE_COLUMNS
    }
    transformer.numeric_medians_ = pd.Series(
        medians,
        index=list(NUMERIC_FEATURE_COLUMNS),
        dtype="float64",
    )

    category_values = {column: sorted(categories[column]) for column in ONE_HOT_COLUMNS}
    empty = [column for column, values in category_values.items() if not values]
    if empty:  # pragma: no cover - normalized categoricals always contain a value
        raise FeatureValidationError(f"Training categoricals contain no values: {empty}")
    longest = max(len(values) for values in category_values.values())
    encoder_training = pd.DataFrame(
        {
            column: values + [values[-1]] * (longest - len(values))
            for column, values in category_values.items()
        }
    )
    transformer.one_hot_encoder_ = _one_hot_encoder()
    transformer.one_hot_encoder_.fit(encoder_training.loc[:, list(ONE_HOT_COLUMNS)])

    transformer.scaler_ = StandardScaler()
    feature_names: tuple[str, ...] | None = None
    training_rows = 0
    for raw_path in _raw_part_paths(raw_root, train_quarters):
        raw = pd.read_parquet(raw_path)
        prepared = transformer._prepare(raw, include_target=False)
        features = transformer._assemble_features(prepared)
        names = tuple(str(column) for column in features.columns)
        if feature_names is None:
            feature_names = names
        elif names != feature_names:
            raise FeatureStoreError("Training feature schema changed between streaming chunks.")
        transformer.scaler_.partial_fit(features.astype("float64"))
        training_rows += len(features)
        del raw, prepared, features

    if feature_names is None:  # pragma: no cover - guarded above
        raise FeatureValidationError("The temporal training window contains no features.")
    transformer.feature_names_ = feature_names
    transformer.training_row_count_ = training_rows
    transformer.training_issue_quarters_ = tuple(train_quarters)
    transformer.fitted_at_utc_ = datetime.now(UTC).isoformat()
    transformer._is_fitted = True
    shutil.rmtree(numeric_root)
    gc.collect()
    return transformer


def _build_streaming_dictionary(
    *,
    feature_names: Sequence[str],
    feature_dtypes: dict[str, str],
    numeric_missing_counts: Counter[str],
    raw_missing_counts: dict[str, int],
    resolved_rows: int,
) -> pd.DataFrame:
    raw_rates = {
        column: count / resolved_rows for column, count in raw_missing_counts.items()
    }
    numeric_rates = {
        feature: numeric_missing_counts[feature] / resolved_rows
        for feature in NUMERIC_FEATURE_COLUMNS
    }
    rows: list[dict[str, object]] = []
    for feature_name in feature_names:
        source_column = _source_for_feature(feature_name)
        base_feature = feature_name.removesuffix("_was_missing")
        if base_feature in numeric_rates:
            null_rate: float | None = numeric_rates[base_feature]
        else:
            rates = [
                raw_rates[item]
                for item in source_column.split("|")
                if item in raw_rates
            ]
            null_rate = max(rates) if rates else None
        rows.append(
            {
                "feature_name": feature_name,
                "dtype": feature_dtypes[feature_name],
                "source_column": source_column,
                "null_rate": null_rate,
                "transformation_applied": _transformation_for_feature(feature_name),
                "leakage_risk_flag": False,
            }
        )

    metadata_rows = (
        (
            TARGET_COLUMN,
            "int8",
            TARGET_SOURCE_COLUMN,
            "map Charged Off or Default to 1 and Fully Paid to 0; exclude unresolved outcomes",
        ),
        (
            ISSUE_DATE_COLUMN,
            "datetime64[ns]",
            ISSUE_DATE_COLUMN,
            "parse issue month; derive partition quarter; exclude from model matrix",
        ),
        (
            EARLIEST_CREDIT_COLUMN,
            "datetime64[ns]",
            EARLIEST_CREDIT_COLUMN,
            "derive credit_history_years; exclude raw date from model matrix",
        ),
    )
    for feature_name, dtype, source_column, transformation in metadata_rows:
        rows.append(
            {
                "feature_name": feature_name,
                "dtype": dtype,
                "source_column": source_column,
                "null_rate": raw_rates.get(source_column),
                "transformation_applied": transformation,
                "leakage_risk_flag": True,
            }
        )
    for column in sorted(LEAKAGE_COLUMNS):
        rows.append(
            {
                "feature_name": column,
                "dtype": "excluded",
                "source_column": column,
                "null_rate": raw_rates.get(column),
                "transformation_applied": "excluded post-origination field",
                "leakage_risk_flag": True,
            }
        )
    return pd.DataFrame(rows, columns=DATA_DICTIONARY_COLUMNS)


def _write_transformed_partitions(
    raw_root: Path,
    output_root: Path,
    *,
    transformer: LoanFeatureTransformer,
    split_metadata: TemporalSplitMetadata,
) -> tuple[dict[str, str], Counter[str]]:
    quarter_to_split = {
        **{quarter: "train" for quarter in split_metadata.train_quarters},
        **{quarter: "validation" for quarter in split_metadata.validation_quarters},
        **{quarter: "shift" for quarter in split_metadata.shift_quarters},
    }
    feature_dtypes: dict[str, str] | None = None
    numeric_missing: Counter[str] = Counter()

    for quarter in sorted(quarter_to_split):
        split_name = quarter_to_split[quarter]
        unscaled_path = (
            output_root
            / "unscaled"
            / f"{ISSUE_QUARTER_COLUMN}={quarter}"
            / "part-00000.parquet"
        )
        scaled_path = (
            output_root
            / "scaled"
            / f"{ISSUE_QUARTER_COLUMN}={quarter}"
            / "part-00000.parquet"
        )
        unscaled_writer = _ParquetAppender(unscaled_path)
        scaled_writer = _ParquetAppender(scaled_path)
        try:
            for raw_path in _raw_part_paths(raw_root, (quarter,)):
                raw = pd.read_parquet(raw_path)
                transformed = transformer.transform(raw, include_target=True)
                if feature_dtypes is None:
                    feature_dtypes = {
                        str(column): str(dtype)
                        for column, dtype in transformed.features.dtypes.items()
                    }
                for feature in NUMERIC_FEATURE_COLUMNS:
                    flag = missing_flag_name(feature)
                    numeric_missing[feature] += int(transformed.features[flag].sum())

                unscaled = _dataset_frame(
                    transformed,
                    split_name=split_name,
                    scaled=False,
                )
                unscaled_writer.append(unscaled.drop(columns=[ISSUE_QUARTER_COLUMN]))
                del unscaled
                scaled = _dataset_frame(
                    transformed,
                    split_name=split_name,
                    scaled=True,
                )
                scaled_writer.append(scaled.drop(columns=[ISSUE_QUARTER_COLUMN]))
                del raw, transformed, scaled
        finally:
            unscaled_writer.close()
            scaled_writer.close()

    if feature_dtypes is None:  # pragma: no cover - resolved rows guarantee output
        raise FeatureStoreError("No transformed rows were written.")
    return feature_dtypes, numeric_missing


def _promote(staging: Path, destination: Path, *, overwrite: bool) -> None:
    if destination.exists():
        if not overwrite:
            raise FeatureStoreError(
                f"Feature-store destination already exists: {destination}. "
                "Pass overwrite=True to replace it explicitly."
            )
        shutil.rmtree(destination)
    os.replace(staging, destination)


def build_streaming_feature_store(
    input_csv: str | Path | Sequence[str | Path],
    feature_store: str | Path,
    *,
    artifact_directory: str | Path | None = None,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    shift_fraction: float | None = None,
    chunk_size: int | None = None,
    random_seed: int | None = None,
    overwrite: bool = False,
    parquet_engine: str = "pyarrow",
) -> StreamingBuildResult:
    """Build a complete feature store without retaining the full CSV in RAM."""

    if chunk_size is not None and (isinstance(chunk_size, bool) or chunk_size <= 0):
        raise ValueError("chunk_size must be a positive integer or None.")
    if parquet_engine != "pyarrow":
        raise FeatureStoreError(
            "The bounded-memory build path requires parquet_engine='pyarrow'."
        )
    effective_chunk_size = chunk_size or _DEFAULT_CHUNK_SIZE
    sources = _normalise_sources(input_csv)
    destination = Path(feature_store).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FeatureStoreError(
            f"Feature-store destination already exists: {destination}. "
            "Pass overwrite=True to replace it explicitly."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    work_root = staging / _WORK_DIRECTORY
    raw_root = work_root / "raw"
    raw_root.mkdir(parents=True)

    try:
        spool = _spool_resolved_rows(
            sources,
            raw_root,
            chunk_size=effective_chunk_size,
            requested_chunk_size=chunk_size,
        )
        temporal = _temporal_metadata(
            spool,
            train_fraction=train_fraction,
            validation_fraction=validation_fraction,
            shift_fraction=shift_fraction,
        )
        transformer = _fit_transformer_streaming(
            raw_root,
            temporal.train_quarters,
            work_root,
        )
        feature_dtypes, numeric_missing = _write_transformed_partitions(
            raw_root,
            staging,
            transformer=transformer,
            split_metadata=temporal,
        )

        data_dictionary = _build_streaming_dictionary(
            feature_names=transformer.feature_names_,
            feature_dtypes=feature_dtypes,
            numeric_missing_counts=numeric_missing,
            raw_missing_counts=spool.raw_missing_counts,
            resolved_rows=spool.resolved_rows,
        )
        dictionary_relative = "data_dictionary.csv"
        data_dictionary.to_csv(staging / dictionary_relative, index=False)
        transformer.save_artifacts(staging / "artifacts")
        artifact_sha256 = {
            path.name: _sha256_file(path)
            for path in sorted((staging / "artifacts").iterdir())
            if path.is_file()
        }
        quarter_to_split = {
            **{quarter: "train" for quarter in temporal.train_quarters},
            **{quarter: "validation" for quarter in temporal.validation_quarters},
            **{quarter: "shift" for quarter in temporal.shift_quarters},
        }
        manifest: dict[str, Any] = {
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
            "variants": ["unscaled", "scaled"],
            "feature_names": list(transformer.feature_names_),
            "feature_dtypes": feature_dtypes,
            "row_counts": temporal.row_counts,
            "total_rows": int(sum(temporal.row_counts.values())),
            "partitions": list(spool.quarters),
            "minimum_issue_quarter": min(spool.quarters),
            "maximum_issue_quarter": max(spool.quarters),
            "quarter_to_split": quarter_to_split,
            "artifact_directory": "artifacts",
            "artifact_sha256": artifact_sha256,
            "data_dictionary": dictionary_relative,
            "data_dictionary_sha256": _sha256_file(staging / dictionary_relative),
            "pipeline_metadata": {
                "ingestion": spool.ingestion.to_dict(),
                "temporal_split": temporal.to_dict(),
                "chunk_size": chunk_size,
                "effective_chunk_size": effective_chunk_size,
                "random_seed": random_seed,
                "fit_scope": "train_only",
                "execution_mode": "streaming",
                "normalized_status_counts": spool.status_counts,
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(_json_safe(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(work_root)
        _promote(staging, destination, overwrite=overwrite)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    internal_artifacts = destination / "artifacts"
    selected_artifacts = internal_artifacts
    if artifact_directory is not None:
        requested = Path(artifact_directory).expanduser().resolve()
        if requested != internal_artifacts:
            transformer.save_artifacts(requested, overwrite=overwrite)
        selected_artifacts = requested

    return StreamingBuildResult(
        root=destination,
        manifest_path=destination / "manifest.json",
        artifact_directory=selected_artifacts,
        data_dictionary_path=destination / dictionary_relative,
        ingestion=spool.ingestion,
        temporal_split=temporal,
        feature_names=transformer.feature_names_,
    )

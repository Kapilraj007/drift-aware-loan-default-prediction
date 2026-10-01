"""Time-window slicing and deterministic synthetic drift generation."""

from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from numbers import Integral
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from .models import (
    NumericSummary,
    PerturbationReport,
    PerturbationSpec,
    ShiftMode,
    SimulationManifest,
    SimulationResult,
    TimeWindow,
)

DEFAULT_METADATA_COLUMNS: tuple[str, ...] = (
    "issue_d",
    "issue_quarter",
    "dataset_split",
)


@dataclass(slots=True)
class FeatureStoreSlice:
    """A copied feature-store window plus the provenance needed by a manifest."""

    frame: pd.DataFrame
    source: Path
    feature_view: str | None
    window: TimeWindow
    time_column: str
    rows_read: int
    selected_time_min: str | None
    selected_time_max: str | None
    source_file_count: int
    source_files_sha256: str


def _validate_column_name(value: str | None, *, name: str, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        suffix = " or None" if allow_none else ""
        raise ValueError(f"{name} must be a non-empty string{suffix}")


def _parse_time_column(frame: pd.DataFrame, time_column: str) -> pd.Series:
    if time_column not in frame.columns:
        raise KeyError(f"time column {time_column!r} is missing from the feature store")
    parsed = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
    invalid = parsed.isna()
    if invalid.any():
        raise ValueError(
            f"time column {time_column!r} contains {int(invalid.sum())} missing or invalid values"
        )
    return parsed


def _window_mask(times: pd.Series, window: TimeWindow) -> pd.Series:
    mask = pd.Series(True, index=times.index, dtype=bool)
    if window.start is not None:
        comparison = times.ge(window.start) if window.include_start else times.gt(window.start)
        mask &= comparison
    if window.end is not None:
        comparison = times.le(window.end) if window.include_end else times.lt(window.end)
        mask &= comparison
    return mask


def _resolve_dataset_path(source: Path, feature_view: str | None) -> tuple[Path, str | None]:
    if not source.exists():
        raise FileNotFoundError(f"feature store does not exist: {source}")
    if source.is_file():
        if source.suffix.lower() != ".parquet":
            raise ValueError("feature store file must end with .parquet")
        return source, None
    if feature_view is not None:
        _validate_column_name(feature_view, name="feature_view")
        candidate = source / feature_view
        if candidate.is_dir():
            return candidate, feature_view
    return source, None


def _parquet_inventory(dataset_path: Path) -> tuple[list[Path], str]:
    files = (
        [dataset_path]
        if dataset_path.is_file()
        else sorted(path for path in dataset_path.rglob("*.parquet") if path.is_file())
    )
    if not files:
        raise FileNotFoundError(f"no Parquet files found below: {dataset_path}")
    base = dataset_path.parent if dataset_path.is_file() else dataset_path
    digest = hashlib.sha256()
    for path in files:
        relative_name = path.relative_to(base).as_posix()
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return files, digest.hexdigest()


def load_feature_window(
    store_path: str | Path,
    *,
    window: TimeWindow | None = None,
    time_column: str = "issue_d",
    feature_view: str | None = "unscaled",
) -> FeatureStoreSlice:
    """Load a partitioned Parquet store and select an exact time window.

    ``store_path`` may be a Parquet file, a partitioned dataset directory, or
    the feature-store root. When the root contains an ``unscaled`` view, that
    view is selected by default so interest-rate and DTI shifts remain in their
    natural units. The returned frame owns its data and keeps the source order
    and index.
    """

    _validate_column_name(time_column, name="time_column")
    selected_window = window if window is not None else TimeWindow()
    if not isinstance(selected_window, TimeWindow):
        raise TypeError("window must be a TimeWindow or None")

    requested_source = Path(store_path).expanduser()
    dataset_path, resolved_view = _resolve_dataset_path(requested_source, feature_view)
    files, files_digest = _parquet_inventory(dataset_path)

    frame = pd.read_parquet(dataset_path)
    if not frame.columns.is_unique:
        raise ValueError("feature-store columns must be unique")
    parsed_times = _parse_time_column(frame, time_column)
    mask = _window_mask(parsed_times, selected_window)
    selected = frame.loc[mask].copy(deep=True)
    selected.attrs = copy.deepcopy(frame.attrs)
    selected_times = parsed_times.loc[mask]

    return FeatureStoreSlice(
        frame=selected,
        source=dataset_path.resolve(),
        feature_view=resolved_view,
        window=selected_window,
        time_column=time_column,
        rows_read=len(frame),
        selected_time_min=(
            selected_times.min().isoformat() if not selected_times.empty else None
        ),
        selected_time_max=(
            selected_times.max().isoformat() if not selected_times.empty else None
        ),
        source_file_count=len(files),
        source_files_sha256=files_digest,
    )


def slice_feature_store(
    store_path: str | Path,
    *,
    window: TimeWindow | None = None,
    time_column: str = "issue_d",
    feature_view: str | None = "unscaled",
) -> pd.DataFrame:
    """Convenience wrapper returning only the independent window frame."""

    return load_feature_window(
        store_path,
        window=window,
        time_column=time_column,
        feature_view=feature_view,
    ).frame


def _normalise_metadata_columns(metadata_columns: Iterable[str]) -> tuple[str, ...]:
    if isinstance(metadata_columns, str):
        raise TypeError("metadata_columns must be an iterable of column names, not a string")
    result: list[str] = []
    seen: set[str] = set()
    for column in metadata_columns:
        _validate_column_name(column, name="metadata column")
        if column not in seen:
            result.append(column)
            seen.add(column)
    return tuple(result)


def _validate_simulation_inputs(
    frame: pd.DataFrame,
    perturbations: Sequence[PerturbationSpec],
    *,
    seed: int,
    target_column: str | None,
    metadata_columns: tuple[str, ...],
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise ValueError("frame columns must be unique")
    if isinstance(seed, bool) or not isinstance(seed, Integral):
        raise TypeError("seed must be a non-negative integer")
    if seed < 0:
        raise ValueError("seed must be a non-negative integer")
    _validate_column_name(target_column, name="target_column", allow_none=True)

    protected = set(metadata_columns)
    if target_column is not None:
        protected.add(target_column)
    missing_protected = sorted(protected.difference(frame.columns))
    if missing_protected:
        names = ", ".join(missing_protected)
        raise KeyError(f"protected column(s) missing from frame: {names}")

    for index, spec in enumerate(perturbations):
        if not isinstance(spec, PerturbationSpec):
            raise TypeError(f"perturbations[{index}] must be a PerturbationSpec")
        if spec.feature in protected:
            raise ValueError(f"perturbation feature {spec.feature!r} is a protected column")
        if spec.feature not in frame.columns:
            raise KeyError(f"perturbation feature {spec.feature!r} is missing from frame")
        series = frame[spec.feature]
        if is_bool_dtype(series.dtype) or not is_numeric_dtype(series.dtype):
            raise TypeError(f"perturbation feature {spec.feature!r} must be numeric")


def _sample_size(eligible_rows: int, fraction: float) -> int:
    if eligible_rows == 0 or fraction == 0:
        return 0
    # Round halves upward and ensure any positive requested fraction has an effect.
    rounded = math.floor(eligible_rows * fraction + 0.5)
    return min(eligible_rows, max(1, rounded))


def _apply_one(
    frame: pd.DataFrame,
    spec: PerturbationSpec,
    *,
    seed: int,
    operation_index: int,
) -> PerturbationReport:
    before = NumericSummary.from_series(frame[spec.feature])
    numeric = pd.to_numeric(frame[spec.feature], errors="raise")
    values = numeric.to_numpy(dtype=np.float64, na_value=np.nan)
    eligible_positions = np.flatnonzero(np.isfinite(values))
    selected_count = _sample_size(len(eligible_positions), spec.fraction)

    if selected_count == len(eligible_positions):
        selected_positions = eligible_positions.copy()
    elif selected_count == 0:
        selected_positions = np.empty(0, dtype=np.int64)
    else:
        rng = np.random.default_rng(np.random.SeedSequence([seed, operation_index]))
        selected_positions = np.sort(
            rng.choice(eligible_positions, size=selected_count, replace=False)
        )

    updated_values = values.copy()
    original_selected = updated_values[selected_positions].copy()
    if spec.mode is ShiftMode.ABSOLUTE:
        shifted = original_selected + spec.shift
    else:
        shifted = original_selected * (1.0 + spec.shift)

    if spec.clip is not None:
        lower, upper = spec.clip
        shifted = np.clip(
            shifted,
            -np.inf if lower is None else lower,
            np.inf if upper is None else upper,
        )
    updated_values[selected_positions] = shifted
    changed_rows = int(np.count_nonzero(original_selected != shifted))
    if changed_rows:
        # A NumPy array assigns positionally, including when the frame index is duplicated.
        frame[spec.feature] = updated_values
    after = NumericSummary.from_series(frame[spec.feature])
    return PerturbationReport(
        specification=spec,
        eligible_rows=len(eligible_positions),
        selected_rows=selected_count,
        changed_rows=changed_rows,
        selected_positions_sha256=PerturbationReport.digest_positions(selected_positions),
        before=before,
        after=after,
    )


def apply_perturbations(
    frame: pd.DataFrame,
    perturbations: Sequence[PerturbationSpec] = (),
    *,
    seed: int = 0,
    target_column: str | None = "target",
    metadata_columns: Iterable[str] = (),
) -> SimulationResult:
    """Apply synthetic drift to an independent deep copy of ``frame``.

    Only ``int_rate`` and ``dti`` can be changed. Target and declared metadata
    columns are validated as protected, and every other column remains untouched.
    Operation-specific random streams are derived from ``seed`` and operation
    position, making repeated runs byte-for-byte reproducible at the value level.
    """

    seed = int(seed) if isinstance(seed, Integral) and not isinstance(seed, bool) else seed
    specs = tuple(perturbations)
    metadata = _normalise_metadata_columns(metadata_columns)
    _validate_simulation_inputs(
        frame,
        specs,
        seed=seed,
        target_column=target_column,
        metadata_columns=metadata,
    )

    working = frame.copy(deep=True)
    working.attrs = copy.deepcopy(frame.attrs)
    affected_features = tuple(dict.fromkeys(spec.feature for spec in specs))
    before_stats = {
        feature: NumericSummary.from_series(working[feature]) for feature in affected_features
    }
    reports = tuple(
        _apply_one(working, spec, seed=seed, operation_index=index)
        for index, spec in enumerate(specs)
    )
    after_stats = {
        feature: NumericSummary.from_series(working[feature]) for feature in affected_features
    }

    manifest = SimulationManifest(
        schema_version="1.0",
        seed=seed,
        source=None,
        feature_view=None,
        time_column=None,
        target_column=target_column,
        metadata_columns=metadata,
        window=None,
        rows_read=len(frame),
        rows_selected=len(frame),
        selected_time_min=None,
        selected_time_max=None,
        source_file_count=None,
        source_files_sha256=None,
        perturbations=reports,
        before_stats=before_stats,
        after_stats=after_stats,
    )
    return SimulationResult(frame=working, manifest=manifest)


def run_drift_simulation(
    store_path: str | Path,
    *,
    window: TimeWindow | None = None,
    perturbations: Sequence[PerturbationSpec] = (),
    seed: int = 0,
    time_column: str = "issue_d",
    target_column: str | None = "target",
    metadata_columns: Iterable[str] = DEFAULT_METADATA_COLUMNS,
    feature_view: str | None = "unscaled",
) -> SimulationResult:
    """Slice a feature store, perturb the window, and return data plus manifest."""

    store_slice = load_feature_window(
        store_path,
        window=window,
        time_column=time_column,
        feature_view=feature_view,
    )
    result = apply_perturbations(
        store_slice.frame,
        perturbations,
        seed=seed,
        target_column=target_column,
        metadata_columns=metadata_columns,
    )
    result.manifest = replace(
        result.manifest,
        source=str(store_slice.source),
        feature_view=store_slice.feature_view,
        time_column=store_slice.time_column,
        window=store_slice.window,
        rows_read=store_slice.rows_read,
        rows_selected=len(store_slice.frame),
        selected_time_min=store_slice.selected_time_min,
        selected_time_max=store_slice.selected_time_max,
        source_file_count=store_slice.source_file_count,
        source_files_sha256=store_slice.source_files_sha256,
    )
    return result

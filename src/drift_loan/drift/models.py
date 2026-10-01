"""Configuration and report models for deterministic drift simulation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from numbers import Real
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd


class ShiftMode(StrEnum):
    """How a synthetic shift is applied to a numeric feature."""

    ABSOLUTE = "absolute"
    RELATIVE = "relative"


def _normalise_timestamp(value: Any, *, field_name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid date or timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field_name} must not be NaT")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


DateLike = str | date | datetime | pd.Timestamp


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A UTC-normalised time interval with independently configurable boundaries.

    The default is the conventional half-open interval ``[start, end)``. ``None``
    leaves that side of the interval unbounded.
    """

    start: DateLike | None = None
    end: DateLike | None = None
    include_start: bool = True
    include_end: bool = False

    def __post_init__(self) -> None:
        start = _normalise_timestamp(self.start, field_name="start")
        end = _normalise_timestamp(self.end, field_name="end")
        if start is not None and end is not None and start > end:
            raise ValueError("start must be earlier than or equal to end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "start": self.start.isoformat() if self.start is not None else None,
            "end": self.end.isoformat() if self.end is not None else None,
            "include_start": self.include_start,
            "include_end": self.include_end,
        }


@dataclass(frozen=True, slots=True)
class PerturbationSpec:
    """A reproducible synthetic shift applied to ``int_rate`` or ``dti``.

    ``absolute`` adds ``shift`` in the feature's stored units. ``relative``
    multiplies values by ``1 + shift``; for example, ``shift=0.15`` models a
    15 percent increase. The row fraction is sampled without replacement from
    finite, non-null values only.
    """

    SUPPORTED_FEATURES: ClassVar[frozenset[str]] = frozenset({"int_rate", "dti"})

    feature: str
    shift: float
    mode: ShiftMode | str = ShiftMode.ABSOLUTE
    fraction: float = 1.0
    clip: tuple[float | None, float | None] | None = None

    def __post_init__(self) -> None:
        if self.feature not in self.SUPPORTED_FEATURES:
            supported = ", ".join(sorted(self.SUPPORTED_FEATURES))
            raise ValueError(f"feature must be one of: {supported}")

        try:
            mode = ShiftMode(self.mode)
        except ValueError as exc:
            choices = ", ".join(item.value for item in ShiftMode)
            raise ValueError(f"mode must be one of: {choices}") from exc
        object.__setattr__(self, "mode", mode)

        if isinstance(self.shift, bool) or not isinstance(self.shift, Real):
            raise TypeError("shift must be a finite number")
        shift = float(self.shift)
        if not math.isfinite(shift):
            raise ValueError("shift must be finite")
        object.__setattr__(self, "shift", shift)

        if isinstance(self.fraction, bool) or not isinstance(self.fraction, Real):
            raise TypeError("fraction must be a number between 0 and 1")
        fraction = float(self.fraction)
        if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be between 0 and 1 inclusive")
        object.__setattr__(self, "fraction", fraction)

        if self.clip is None:
            return
        if not isinstance(self.clip, tuple) or len(self.clip) != 2:
            raise TypeError("clip must be a (lower, upper) tuple or None")
        lower, upper = self.clip
        normalised: list[float | None] = []
        for name, bound in (("lower", lower), ("upper", upper)):
            if bound is None:
                normalised.append(None)
                continue
            if isinstance(bound, bool) or not isinstance(bound, Real):
                raise TypeError(f"clip {name} bound must be a finite number or None")
            value = float(bound)
            if not math.isfinite(value):
                raise ValueError(f"clip {name} bound must be finite")
            normalised.append(value)
        if normalised[0] is not None and normalised[1] is not None:
            if normalised[0] > normalised[1]:
                raise ValueError("clip lower bound must not exceed upper bound")
        object.__setattr__(self, "clip", (normalised[0], normalised[1]))

    @classmethod
    def absolute(
        cls,
        feature: str,
        shift: float,
        *,
        fraction: float = 1.0,
        clip: tuple[float | None, float | None] | None = None,
    ) -> PerturbationSpec:
        return cls(
            feature=feature,
            shift=shift,
            mode=ShiftMode.ABSOLUTE,
            fraction=fraction,
            clip=clip,
        )

    @classmethod
    def relative(
        cls,
        feature: str,
        shift: float,
        *,
        fraction: float = 1.0,
        clip: tuple[float | None, float | None] | None = None,
    ) -> PerturbationSpec:
        return cls(
            feature=feature,
            shift=shift,
            mode=ShiftMode.RELATIVE,
            fraction=fraction,
            clip=clip,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "shift": self.shift,
            "mode": self.mode.value,
            "fraction": self.fraction,
            "clip": list(self.clip) if self.clip is not None else None,
        }


@dataclass(frozen=True, slots=True)
class NumericSummary:
    """JSON-safe descriptive statistics computed over finite values."""

    row_count: int
    non_null_count: int
    missing_count: int
    finite_count: int
    non_finite_count: int
    mean: float | None
    std: float | None
    minimum: float | None
    q25: float | None
    median: float | None
    q75: float | None
    maximum: float | None

    @classmethod
    def from_series(cls, series: pd.Series) -> NumericSummary:
        numeric = pd.to_numeric(series, errors="raise")
        values = numeric.to_numpy(dtype=np.float64, na_value=np.nan)
        missing = pd.isna(numeric).to_numpy(dtype=bool)
        finite = np.isfinite(values)
        finite_values = values[finite]
        non_null_count = int((~missing).sum())
        non_finite_count = int((~missing & ~finite).sum())

        if finite_values.size == 0:
            stats: tuple[float | None, ...] = (None,) * 7
        else:
            quantiles = np.quantile(finite_values, [0.25, 0.5, 0.75])
            stats = (
                float(np.mean(finite_values)),
                float(np.std(finite_values, ddof=0)),
                float(np.min(finite_values)),
                float(quantiles[0]),
                float(quantiles[1]),
                float(quantiles[2]),
                float(np.max(finite_values)),
            )

        return cls(
            row_count=len(series),
            non_null_count=non_null_count,
            missing_count=int(missing.sum()),
            finite_count=int(finite.sum()),
            non_finite_count=non_finite_count,
            mean=stats[0],
            std=stats[1],
            minimum=stats[2],
            q25=stats[3],
            median=stats[4],
            q75=stats[5],
            maximum=stats[6],
        )


@dataclass(frozen=True, slots=True)
class PerturbationReport:
    """Audit details for one perturbation operation."""

    specification: PerturbationSpec
    eligible_rows: int
    selected_rows: int
    changed_rows: int
    selected_positions_sha256: str
    before: NumericSummary
    after: NumericSummary

    @staticmethod
    def digest_positions(positions: np.ndarray) -> str:
        stable_bytes = np.asarray(positions, dtype=">i8").tobytes()
        return hashlib.sha256(stable_bytes).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "specification": self.specification.to_dict(),
            "eligible_rows": self.eligible_rows,
            "selected_rows": self.selected_rows,
            "changed_rows": self.changed_rows,
            "selected_positions_sha256": self.selected_positions_sha256,
            "before": asdict(self.before),
            "after": asdict(self.after),
        }


@dataclass(frozen=True, slots=True)
class SimulationManifest:
    """Serializable provenance and before/after report for a simulation run."""

    schema_version: str
    seed: int
    source: str | None
    feature_view: str | None
    time_column: str | None
    target_column: str | None
    metadata_columns: tuple[str, ...]
    window: TimeWindow | None
    rows_read: int
    rows_selected: int
    selected_time_min: str | None
    selected_time_max: str | None
    source_file_count: int | None
    source_files_sha256: str | None
    perturbations: tuple[PerturbationReport, ...] = field(default_factory=tuple)
    before_stats: dict[str, NumericSummary] = field(default_factory=dict)
    after_stats: dict[str, NumericSummary] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "source": self.source,
            "feature_view": self.feature_view,
            "time_column": self.time_column,
            "target_column": self.target_column,
            "metadata_columns": list(self.metadata_columns),
            "window": self.window.to_dict() if self.window is not None else None,
            "rows_read": self.rows_read,
            "rows_selected": self.rows_selected,
            "selected_time_min": self.selected_time_min,
            "selected_time_max": self.selected_time_max,
            "source_file_count": self.source_file_count,
            "source_files_sha256": self.source_files_sha256,
            "perturbations": [report.to_dict() for report in self.perturbations],
            "before_stats": {
                feature: asdict(summary) for feature, summary in self.before_stats.items()
            },
            "after_stats": {
                feature: asdict(summary) for feature, summary in self.after_stats.items()
            },
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Return deterministic, strict JSON (NaN/Infinity are never emitted)."""

        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            indent=indent,
            sort_keys=True,
        )

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{self.to_json()}\n", encoding="utf-8")
        return destination


@dataclass(slots=True)
class SimulationResult:
    """The simulated frame and the audit manifest that describes it."""

    frame: pd.DataFrame
    manifest: SimulationManifest

    def write(
        self,
        data_path: str | Path,
        *,
        manifest_path: str | Path | None = None,
        index: bool = False,
    ) -> tuple[Path, Path]:
        """Persist a single Parquet file and its adjacent JSON manifest."""

        destination = Path(data_path)
        if destination.suffix.lower() != ".parquet":
            raise ValueError("data_path must end with .parquet")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.frame.to_parquet(destination, index=index)
        report_path = (
            Path(manifest_path)
            if manifest_path is not None
            else destination.with_suffix(".manifest.json")
        )
        self.manifest.write_json(report_path)
        return destination, report_path

    def copy(self) -> SimulationResult:
        """Return an independent result frame while reusing the immutable report."""

        cloned = self.frame.copy(deep=True)
        cloned.attrs = copy.deepcopy(self.frame.attrs)
        return SimulationResult(frame=cloned, manifest=self.manifest)

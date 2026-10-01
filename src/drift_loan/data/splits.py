"""Deterministic quarter-aligned temporal dataset splitting."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .exceptions import FeatureValidationError, SchemaValidationError
from .schema import ISSUE_DATE_COLUMN, TARGET_SOURCE_COLUMN
from .transform import parse_lendingclub_dates, resolve_loan_outcomes


@dataclass(frozen=True)
class TemporalSplitMetadata:
    """Boundaries and counts for one reproducible temporal split."""

    train_fraction: float
    validation_fraction: float
    shift_fraction: float
    train_quarters: tuple[str, ...]
    validation_quarters: tuple[str, ...]
    shift_quarters: tuple[str, ...]
    row_counts: dict[str, int]
    dropped_unresolved_rows: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TemporalSplit:
    """Raw resolved rows divided into non-overlapping chronological windows."""

    train: pd.DataFrame
    validation: pd.DataFrame
    shift: pd.DataFrame
    metadata: TemporalSplitMetadata

    def as_mapping(self) -> Mapping[str, pd.DataFrame]:
        return {
            "train": self.train,
            "validation": self.validation,
            "shift": self.shift,
        }


def _validate_fractions(
    train_fraction: float,
    validation_fraction: float,
    shift_fraction: float | None,
) -> float:
    resolved_shift = 1.0 - train_fraction - validation_fraction
    values = {
        "train_fraction": train_fraction,
        "validation_fraction": validation_fraction,
        "shift_fraction": resolved_shift if shift_fraction is None else shift_fraction,
    }
    invalid = {name: value for name, value in values.items() if not 0 < value < 1}
    if invalid:
        raise ValueError(f"Temporal split fractions must lie strictly between 0 and 1: {invalid}")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction + validation_fraction must be less than 1.")
    if shift_fraction is not None and not math.isclose(
        train_fraction + validation_fraction + shift_fraction,
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError("train, validation, and shift fractions must sum to 1.")
    return resolved_shift if shift_fraction is None else shift_fraction


def _allocate_quarters(
    quarter_count: int,
    *,
    train_fraction: float,
    validation_fraction: float,
) -> tuple[int, int]:
    if quarter_count < 3:
        raise FeatureValidationError(
            "Temporal train/validation/shift splitting requires at least three distinct "
            f"issue quarters; found {quarter_count}."
        )

    train_count = max(1, math.floor(quarter_count * train_fraction))
    validation_count = max(1, math.floor(quarter_count * validation_fraction))

    # Reserve at least one complete latest quarter for the shift holdout.
    while train_count + validation_count >= quarter_count:
        if train_count >= validation_count and train_count > 1:
            train_count -= 1
        elif validation_count > 1:
            validation_count -= 1
        else:  # guarded by quarter_count >= 3
            break
    return train_count, validation_count


def temporal_train_validation_shift_split(
    frame: pd.DataFrame,
    *,
    date_column: str = ISSUE_DATE_COLUMN,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    shift_fraction: float | None = None,
    resolved_only: bool = True,
) -> TemporalSplit:
    """Split rows by complete issue quarters, earliest to latest.

    Fractions allocate *quarters*, not individual rows.  A quarter can therefore
    never straddle two datasets, which is the core control needed for honest
    temporal drift evaluation.
    """

    resolved_shift_fraction = _validate_fractions(
        train_fraction,
        validation_fraction,
        shift_fraction,
    )
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise SchemaValidationError("Temporal split input must be a non-empty DataFrame.")
    if date_column not in frame.columns:
        raise SchemaValidationError(f"Temporal split input is missing {date_column!r}.")

    dropped_unresolved = 0
    if resolved_only:
        if TARGET_SOURCE_COLUMN not in frame.columns:
            raise SchemaValidationError(
                f"resolved_only=True requires {TARGET_SOURCE_COLUMN!r} in the split input."
            )
        resolution = resolve_loan_outcomes(frame)
        working = resolution.frame
        dropped_unresolved = resolution.dropped_unresolved_rows
    else:
        working = frame.copy()

    parsed_dates = parse_lendingclub_dates(working[date_column], field_name=date_column)
    if bool(parsed_dates.isna().any()):
        rows = working.index[parsed_dates.isna()].tolist()[:10]
        raise FeatureValidationError(
            f"Temporal split requires non-missing {date_column!r}; missing at indexes {rows}."
        )

    order = np.argsort(parsed_dates.to_numpy(), kind="stable")
    sorted_frame = working.iloc[order].reset_index(drop=True)
    sorted_dates = parsed_dates.iloc[order].reset_index(drop=True)
    quarter_periods = sorted_dates.dt.to_period("Q")
    unique_quarters = tuple(sorted(quarter_periods.unique()))
    train_count, validation_count = _allocate_quarters(
        len(unique_quarters),
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )

    train_periods = unique_quarters[:train_count]
    validation_periods = unique_quarters[train_count : train_count + validation_count]
    shift_periods = unique_quarters[train_count + validation_count :]

    def select(periods: tuple[pd.Period, ...]) -> pd.DataFrame:
        mask = quarter_periods.isin(periods)
        return sorted_frame.loc[mask.to_numpy()].reset_index(drop=True).copy()

    train = select(train_periods)
    validation = select(validation_periods)
    shift = select(shift_periods)
    if train.empty or validation.empty or shift.empty:
        raise FeatureValidationError(
            "Quarter allocation yielded an empty temporal partition; check issue-date coverage."
        )

    metadata = TemporalSplitMetadata(
        train_fraction=float(train_fraction),
        validation_fraction=float(validation_fraction),
        shift_fraction=float(resolved_shift_fraction),
        train_quarters=tuple(str(period) for period in train_periods),
        validation_quarters=tuple(str(period) for period in validation_periods),
        shift_quarters=tuple(str(period) for period in shift_periods),
        row_counts={
            "train": len(train),
            "validation": len(validation),
            "shift": len(shift),
        },
        dropped_unresolved_rows=dropped_unresolved,
    )
    return TemporalSplit(
        train=train,
        validation=validation,
        shift=shift,
        metadata=metadata,
    )

"""Leakage-safe, shared feature transformation for training and serving."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .exceptions import ArtifactError, FeatureValidationError, SchemaValidationError
from .schema import (
    DEFAULT_STATUSES,
    EARLIEST_CREDIT_COLUMN,
    GRADE_TO_ORDINAL,
    ISSUE_DATE_COLUMN,
    ISSUE_QUARTER_COLUMN,
    LEAKAGE_COLUMNS,
    MISSING_CATEGORY,
    NON_DEFAULT_STATUSES,
    NUMERIC_FEATURE_COLUMNS,
    ONE_HOT_COLUMNS,
    RAW_NUMERIC_COLUMNS,
    RAW_PREDICTOR_COLUMNS,
    REQUIRED_INFERENCE_COLUMNS,
    SCHEMA_VERSION,
    SUB_GRADE_TO_ORDINAL,
    TARGET_SOURCE_COLUMN,
    UNKNOWN_ORDINAL_VALUE,
    missing_flag_name,
)

_TRANSFORMER_FILENAME = "feature_transformer.joblib"
_METADATA_FILENAME = "feature_metadata.json"
_DATE_FORMATS = (
    "%b-%Y",
    "%b-%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)
_MISSING_TEXT_VALUES = frozenset({"", "na", "n/a", "none", "null", "nan", "nat"})


@dataclass(frozen=True)
class TargetResolution:
    """Resolved outcomes and the rows retained for supervised learning."""

    frame: pd.DataFrame
    target: pd.Series
    dropped_unresolved_rows: int
    normalized_status_counts: dict[str, int]


@dataclass(frozen=True)
class TransformedFeatures:
    """Unscaled and standardized views produced from one shared transform."""

    features: pd.DataFrame
    scaled_features: pd.DataFrame
    target: pd.Series | None
    issue_dates: pd.Series
    issue_quarters: pd.Series
    source_index: pd.Index

    def __len__(self) -> int:
        return len(self.features)

    def model_frame(self, *, scaled: bool = False) -> pd.DataFrame:
        """Return a defensive copy of the requested model feature view."""

        source = self.scaled_features if scaled else self.features
        return source.copy()


@dataclass(frozen=True)
class _PreparedFeatures:
    numeric: pd.DataFrame
    ordinal: pd.DataFrame
    categoricals: pd.DataFrame
    target: pd.Series | None
    issue_dates: pd.Series
    issue_quarters: pd.Series
    source_index: pd.Index


def _normalise_status(status: pd.Series) -> pd.Series:
    return status.astype("string").str.strip().str.casefold()


def resolve_loan_outcomes(frame: pd.DataFrame) -> TargetResolution:
    """Map resolved ``loan_status`` values and discard every unresolved row.

    The mapping is deliberately narrow: only ``Charged Off``/``Default`` and
    ``Fully Paid`` are considered resolved outcomes.  Late, current, grace,
    and policy-specific statuses therefore cannot be mislabeled as defaults.
    """

    if TARGET_SOURCE_COLUMN not in frame.columns:
        raise SchemaValidationError(
            f"Training data must contain the target source column {TARGET_SOURCE_COLUMN!r}."
        )

    normalized = _normalise_status(frame[TARGET_SOURCE_COLUMN])
    target = pd.Series(pd.NA, index=frame.index, dtype="Int8", name="target")
    target.loc[normalized.isin(DEFAULT_STATUSES)] = 1
    target.loc[normalized.isin(NON_DEFAULT_STATUSES)] = 0
    resolved_mask = target.notna()

    if not bool(resolved_mask.any()):
        observed = sorted(normalized.dropna().unique().tolist())
        raise FeatureValidationError(
            "No resolved loan outcomes were found. Expected loan_status in "
            f"{sorted(DEFAULT_STATUSES | NON_DEFAULT_STATUSES)}; observed {observed[:10]}."
        )

    counts = {
        str(status): int(count)
        for status, count in normalized.fillna("<missing>").value_counts(dropna=False).items()
    }
    resolved_frame = frame.loc[resolved_mask].copy()
    resolved_target = target.loc[resolved_mask].astype("Int8")
    return TargetResolution(
        frame=resolved_frame,
        target=resolved_target,
        dropped_unresolved_rows=int((~resolved_mask).sum()),
        normalized_status_counts=counts,
    )


def parse_lendingclub_dates(values: pd.Series, *, field_name: str) -> pd.Series:
    """Parse LendingClub month strings and ISO dates without locale inference."""

    if is_datetime64_any_dtype(values.dtype):
        parsed = pd.to_datetime(values, errors="coerce")
        return pd.Series(parsed, index=values.index, name=field_name, dtype="datetime64[ns]")

    text = values.astype("string").str.strip()
    missing = text.isna() | text.str.casefold().isin(_MISSING_TEXT_VALUES)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]", name=field_name)

    for date_format in _DATE_FORMATS:
        remaining = parsed.isna() & ~missing
        if not bool(remaining.any()):
            break
        candidate = pd.to_datetime(text.where(remaining), format=date_format, errors="coerce")
        accepted = remaining & candidate.notna()
        parsed.loc[accepted] = candidate.loc[accepted]

    invalid = ~missing & parsed.isna()
    if bool(invalid.any()):
        examples = text.loc[invalid].drop_duplicates().head(5).tolist()
        raise FeatureValidationError(
            f"Could not parse {field_name!r} as a LendingClub date; invalid examples: {examples}."
        )
    return parsed


def _clean_numeric_text(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    text = values.astype("string").str.strip()
    missing = text.isna() | text.str.casefold().isin(_MISSING_TEXT_VALUES)
    cleaned = (
        text.str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .mask(missing)
    )
    return cleaned, missing


def _coerce_numeric(values: pd.Series, *, field_name: str) -> pd.Series:
    cleaned, missing = _clean_numeric_text(values)
    parsed = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    invalid = ~missing & (parsed.isna() | ~np.isfinite(parsed))
    if bool(invalid.any()):
        examples = cleaned.loc[invalid].drop_duplicates().head(5).tolist()
        raise FeatureValidationError(
            f"Could not parse numeric feature {field_name!r}; invalid examples: {examples}."
        )
    return parsed.mask(~np.isfinite(parsed))


def _parse_percent(values: pd.Series, *, field_name: str) -> pd.Series:
    cleaned, missing = _clean_numeric_text(values)
    cleaned = cleaned.str.replace(r"\s*%$", "", regex=True).mask(missing)
    parsed = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    invalid = ~missing & (parsed.isna() | ~np.isfinite(parsed))
    if bool(invalid.any()):
        examples = values.loc[invalid].astype("string").drop_duplicates().head(5).tolist()
        raise FeatureValidationError(
            f"Could not parse percentage feature {field_name!r}; invalid examples: {examples}."
        )
    return parsed.mask(~np.isfinite(parsed))


def _parse_term(values: pd.Series) -> pd.Series:
    cleaned, missing = _clean_numeric_text(values)
    extracted = cleaned.str.extract(r"^([0-9]+(?:\.0+)?)\s*(?:months?)?$", expand=False)
    parsed = pd.to_numeric(extracted, errors="coerce").astype("float64")
    invalid = ~missing & parsed.isna()
    if bool(invalid.any()):
        examples = values.loc[invalid].astype("string").drop_duplicates().head(5).tolist()
        raise FeatureValidationError(f"Could not parse 'term'; invalid examples: {examples}.")
    return parsed


def _parse_emp_length(values: pd.Series) -> pd.Series:
    cleaned, missing = _clean_numeric_text(values)
    normalized = cleaned.str.casefold().str.replace(r"\s+", " ", regex=True)
    parsed = pd.Series(np.nan, index=values.index, dtype="float64")

    under_one = normalized.str.match(r"^(?:<|less than)\s*1\s*year$", na=False)
    parsed.loc[under_one] = 0.0

    years = normalized.str.extract(r"^([0-9]+(?:\.0+)?)\+?\s*years?$", expand=False)
    years_numeric = pd.to_numeric(years, errors="coerce")
    parsed.loc[years_numeric.notna()] = years_numeric.loc[years_numeric.notna()].astype(float)

    # Numeric API payloads may arrive without a unit.
    plain_numeric = pd.to_numeric(normalized, errors="coerce")
    parsed.loc[plain_numeric.notna()] = plain_numeric.loc[plain_numeric.notna()].astype(float)

    invalid = ~missing & parsed.isna()
    if bool(invalid.any()):
        examples = values.loc[invalid].astype("string").drop_duplicates().head(5).tolist()
        raise FeatureValidationError(
            f"Could not parse 'emp_length' as years; invalid examples: {examples}."
        )
    return parsed


def _normalise_category(values: pd.Series, *, column: str) -> pd.Series:
    normalized = values.astype("string").str.strip()
    missing = normalized.isna() | normalized.str.casefold().isin(_MISSING_TEXT_VALUES)
    if column == "purpose":
        normalized = normalized.str.casefold().str.replace(r"\s+", "_", regex=True)
    elif column == "home_ownership":
        normalized = normalized.str.upper().str.replace(r"\s+", "_", regex=True)
    return normalized.mask(missing, MISSING_CATEGORY).astype(object)


def _one_hot_encoder() -> OneHotEncoder:
    kwargs: dict[str, Any] = {"handle_unknown": "ignore", "dtype": np.float64}
    try:
        return OneHotEncoder(sparse_output=False, **kwargs)
    except TypeError:  # scikit-learn < 1.2
        return OneHotEncoder(sparse=False, **kwargs)


def _feature_schema_hash(feature_names: tuple[str, ...]) -> str:
    payload = "\n".join(feature_names).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class LoanFeatureTransformer:
    """Fitted preprocessing contract shared by training and FastAPI serving.

    Learned state (training medians, one-hot vocabulary, and scaler statistics)
    is fit once on the temporal training partition.  ``transform`` never learns
    or mutates state, which prevents validation/shift or serving data leakage.
    """

    def __init__(self) -> None:
        self._is_fitted = False

    def _prepare(self, raw: pd.DataFrame, *, include_target: bool) -> _PreparedFeatures:
        if not isinstance(raw, pd.DataFrame):
            raise SchemaValidationError("Feature input must be a pandas DataFrame.")
        if raw.empty:
            raise SchemaValidationError("Feature input contains zero rows.")

        missing = sorted(REQUIRED_INFERENCE_COLUMNS - set(raw.columns))
        if missing:
            raise SchemaValidationError(f"Feature input is missing required columns: {missing}")

        if include_target:
            resolution = resolve_loan_outcomes(raw)
            working = resolution.frame
            target = resolution.target
        else:
            working = raw
            target = None

        source_index = working.index.copy()
        issue_dates = parse_lendingclub_dates(
            working[ISSUE_DATE_COLUMN], field_name=ISSUE_DATE_COLUMN
        )
        if bool(issue_dates.isna().any()):
            missing_rows = working.index[issue_dates.isna()].tolist()[:10]
            raise FeatureValidationError(
                f"{ISSUE_DATE_COLUMN!r} is required for every retained row; missing at "
                f"source index values {missing_rows}."
            )
        earliest_dates = parse_lendingclub_dates(
            working[EARLIEST_CREDIT_COLUMN], field_name=EARLIEST_CREDIT_COLUMN
        )

        numeric = pd.DataFrame(index=working.index)
        for column in RAW_NUMERIC_COLUMNS:
            if column == "term":
                numeric[column] = _parse_term(working[column])
            elif column == "emp_length":
                numeric[column] = _parse_emp_length(working[column])
            elif column in {"int_rate", "revol_util"}:
                numeric[column] = _parse_percent(working[column], field_name=column)
            else:
                numeric[column] = _coerce_numeric(working[column], field_name=column)

        positive_income = numeric["annual_inc"].where(numeric["annual_inc"] > 0)
        numeric["loan_to_income"] = numeric["loan_amnt"] / positive_income
        numeric["installment_to_income"] = numeric["installment"] / (positive_income / 12.0)
        history_years = (issue_dates - earliest_dates).dt.total_seconds() / (365.25 * 24 * 3600)
        numeric["credit_history_years"] = history_years.where(history_years >= 0)
        numeric = numeric.replace([np.inf, -np.inf], np.nan)
        numeric = numeric.loc[:, list(NUMERIC_FEATURE_COLUMNS)].astype("float64")

        grade = working["grade"].astype("string").str.strip().str.upper()
        sub_grade = working["sub_grade"].astype("string").str.strip().str.upper()
        ordinal = pd.DataFrame(
            {
                "grade": grade.map(GRADE_TO_ORDINAL).fillna(UNKNOWN_ORDINAL_VALUE).astype("int16"),
                "sub_grade": sub_grade
                .map(SUB_GRADE_TO_ORDINAL)
                .fillna(UNKNOWN_ORDINAL_VALUE)
                .astype("int16"),
            },
            index=working.index,
        )

        categoricals = pd.DataFrame(
            {
                column: _normalise_category(working[column], column=column)
                for column in ONE_HOT_COLUMNS
            },
            index=working.index,
        )

        issue_quarters = issue_dates.dt.to_period("Q").astype(str).rename(ISSUE_QUARTER_COLUMN)
        reset_target = target.reset_index(drop=True) if target is not None else None
        return _PreparedFeatures(
            numeric=numeric.reset_index(drop=True),
            ordinal=ordinal.reset_index(drop=True),
            categoricals=categoricals.reset_index(drop=True),
            target=reset_target,
            issue_dates=issue_dates.reset_index(drop=True).rename(ISSUE_DATE_COLUMN),
            issue_quarters=issue_quarters.reset_index(drop=True),
            source_index=source_index,
        )

    def _assemble_features(self, prepared: _PreparedFeatures) -> pd.DataFrame:
        imputed = prepared.numeric.fillna(self.numeric_medians_).astype("float64")
        missing_flags = prepared.numeric.isna().astype("int8")
        missing_flags.columns = [missing_flag_name(column) for column in missing_flags.columns]

        one_hot_array = self.one_hot_encoder_.transform(prepared.categoricals)
        if hasattr(one_hot_array, "toarray"):
            one_hot_array = one_hot_array.toarray()
        one_hot_names = tuple(
            str(name)
            for name in self.one_hot_encoder_.get_feature_names_out(list(ONE_HOT_COLUMNS))
        )
        one_hot = pd.DataFrame(one_hot_array, columns=one_hot_names, dtype="float64")

        features = pd.concat(
            [
                imputed.reset_index(drop=True),
                missing_flags.reset_index(drop=True),
                prepared.ordinal.reset_index(drop=True),
                one_hot.reset_index(drop=True),
            ],
            axis=1,
        )
        if features.columns.duplicated().any():
            duplicates = features.columns[features.columns.duplicated()].tolist()
            raise FeatureValidationError(f"Duplicate transformed feature names: {duplicates}")

        forbidden = (set(features.columns) & LEAKAGE_COLUMNS) | {
            column
            for column in (TARGET_SOURCE_COLUMN, ISSUE_DATE_COLUMN, EARLIEST_CREDIT_COLUMN)
            if column in features.columns
        }
        if forbidden:
            raise FeatureValidationError(
                f"Leakage or metadata columns reached the model matrix: {sorted(forbidden)}"
            )
        return features

    def fit(self, raw: pd.DataFrame, *, include_target: bool = True) -> LoanFeatureTransformer:
        """Fit medians, one-hot categories, and scaler on training rows only."""

        prepared = self._prepare(raw, include_target=include_target)
        medians = prepared.numeric.median(axis=0, skipna=True)
        all_missing = medians[medians.isna()].index.tolist()
        if all_missing:
            raise FeatureValidationError(
                "Cannot fit median imputation because these training features are entirely "
                f"missing: {all_missing}."
            )

        self.numeric_medians_ = medians.astype("float64")
        self.one_hot_encoder_ = _one_hot_encoder()
        self.one_hot_encoder_.fit(prepared.categoricals)

        features = self._assemble_features(prepared)
        self.feature_names_ = tuple(str(column) for column in features.columns)
        self.scaler_ = StandardScaler()
        self.scaler_.fit(features.astype("float64"))
        self.training_row_count_ = len(features)
        self.training_issue_quarters_ = tuple(sorted(prepared.issue_quarters.unique().tolist()))
        self.fitted_at_utc_ = datetime.now(UTC).isoformat()
        self._is_fitted = True
        return self

    def fit_transform(
        self, raw: pd.DataFrame, *, include_target: bool = True
    ) -> TransformedFeatures:
        """Fit on ``raw`` and return its transformed views."""

        self.fit(raw, include_target=include_target)
        return self.transform(raw, include_target=include_target)

    def transform(
        self, raw: pd.DataFrame, *, include_target: bool = False
    ) -> TransformedFeatures:
        """Apply immutable fitted preprocessing to training or serving rows."""

        self._require_fitted()
        prepared = self._prepare(raw, include_target=include_target)
        features = self._assemble_features(prepared)
        feature_names = tuple(str(column) for column in features.columns)
        if feature_names != self.feature_names_:
            raise ArtifactError(
                "Transformed feature schema differs from the fitted artifact. "
                f"Expected {self.feature_names_}, got {feature_names}."
            )

        scaled_array = self.scaler_.transform(features.astype("float64"))
        scaled = pd.DataFrame(scaled_array, columns=self.feature_names_, dtype="float64")
        return TransformedFeatures(
            features=features.reset_index(drop=True),
            scaled_features=scaled,
            target=prepared.target,
            issue_dates=prepared.issue_dates,
            issue_quarters=prepared.issue_quarters,
            source_index=prepared.source_index,
        )

    def _require_fitted(self) -> None:
        required = (
            "numeric_medians_",
            "one_hot_encoder_",
            "scaler_",
            "feature_names_",
        )
        if not self._is_fitted or any(not hasattr(self, name) for name in required):
            raise ArtifactError(
                "LoanFeatureTransformer is not fitted. Fit it on the temporal training "
                "partition or load a persisted artifact before transforming rows."
            )

    def metadata(self) -> dict[str, object]:
        """Return the complete, JSON-safe fitted preprocessing contract."""

        self._require_fitted()
        categories = {
            column: [str(value) for value in values.tolist()]
            for column, values in zip(
                ONE_HOT_COLUMNS,
                self.one_hot_encoder_.categories_,
                strict=False,
            )
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "LoanFeatureTransformer",
            "fitted_at_utc": self.fitted_at_utc_,
            "training_row_count": int(self.training_row_count_),
            "training_issue_quarters": list(self.training_issue_quarters_),
            "required_raw_columns": list(RAW_PREDICTOR_COLUMNS),
            "numeric_medians": {
                column: float(value) for column, value in self.numeric_medians_.items()
            },
            "one_hot_categories": categories,
            "ordinal_encoding": {
                "grade": dict(GRADE_TO_ORDINAL),
                "sub_grade": dict(SUB_GRADE_TO_ORDINAL),
                "unknown_value": UNKNOWN_ORDINAL_VALUE,
            },
            "feature_names": list(self.feature_names_),
            "feature_schema_sha256": _feature_schema_hash(self.feature_names_),
            "scaler_mean": [float(value) for value in self.scaler_.mean_],
            "scaler_scale": [float(value) for value in self.scaler_.scale_],
            "target_mapping": {
                "default": sorted(DEFAULT_STATUSES),
                "non_default": sorted(NON_DEFAULT_STATUSES),
            },
            "excluded_leakage_columns": sorted(LEAKAGE_COLUMNS),
        }

    def save_artifacts(self, directory: str | Path, *, overwrite: bool = False) -> Path:
        """Persist the fitted transformer and human-readable metadata atomically."""

        self._require_fitted()
        destination = Path(directory).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        transformer_path = destination / _TRANSFORMER_FILENAME
        metadata_path = destination / _METADATA_FILENAME
        existing = [str(path) for path in (transformer_path, metadata_path) if path.exists()]
        if existing and not overwrite:
            raise ArtifactError(
                f"Refusing to overwrite existing preprocessing artifact(s): {existing}"
            )

        transformer_tmp = destination / f".{_TRANSFORMER_FILENAME}.tmp"
        metadata_tmp = destination / f".{_METADATA_FILENAME}.tmp"
        try:
            joblib.dump(self, transformer_tmp)
            metadata_tmp.write_text(
                json.dumps(self.metadata(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(transformer_tmp, transformer_path)
            os.replace(metadata_tmp, metadata_path)
        except Exception as exc:
            transformer_tmp.unlink(missing_ok=True)
            metadata_tmp.unlink(missing_ok=True)
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError(f"Failed to persist preprocessing artifacts: {exc}") from exc
        return destination

    @classmethod
    def load_artifacts(cls, directory: str | Path) -> LoanFeatureTransformer:
        """Load and validate a persisted transformer/metadata pair."""

        source = Path(directory).expanduser().resolve()
        transformer_path = source / _TRANSFORMER_FILENAME
        metadata_path = source / _METADATA_FILENAME
        missing = [str(path) for path in (transformer_path, metadata_path) if not path.is_file()]
        if missing:
            raise ArtifactError(f"Missing preprocessing artifact file(s): {missing}")

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"Invalid preprocessing metadata {metadata_path}: {exc}") from exc
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ArtifactError(
                "Preprocessing artifact schema version mismatch: "
                f"expected {SCHEMA_VERSION!r}, got {metadata.get('schema_version')!r}."
            )

        try:
            transformer = joblib.load(transformer_path)
        except Exception as exc:
            raise ArtifactError(
                f"Could not load transformer artifact {transformer_path}: {exc}"
            ) from exc
        if not isinstance(transformer, cls):
            raise ArtifactError(
                f"Artifact contains {type(transformer).__name__}, expected {cls.__name__}."
            )
        transformer._require_fitted()

        expected_names = tuple(str(name) for name in metadata.get("feature_names", ()))
        expected_hash = metadata.get("feature_schema_sha256")
        actual_hash = _feature_schema_hash(transformer.feature_names_)
        if expected_names != transformer.feature_names_ or expected_hash != actual_hash:
            raise ArtifactError("Transformer and metadata feature schemas do not match.")
        return transformer


def transform_features(
    raw: pd.DataFrame,
    *,
    transformer: LoanFeatureTransformer,
    fit: bool = False,
    include_target: bool = False,
) -> TransformedFeatures:
    """Single train/serve entry point for feature transformation.

    Training code passes ``fit=True`` exactly once on the temporal training
    partition.  Validation, shift, and FastAPI callers pass the same loaded
    transformer with ``fit=False``.
    """

    if not isinstance(transformer, LoanFeatureTransformer):
        raise TypeError("transformer must be a LoanFeatureTransformer instance")
    if fit:
        return transformer.fit_transform(raw, include_target=include_target)
    return transformer.transform(raw, include_target=include_target)


def load_transformer(directory: str | Path) -> LoanFeatureTransformer:
    """Load the fitted shared transform used by the inference service."""

    return LoanFeatureTransformer.load_artifacts(directory)

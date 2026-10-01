"""Generate a run-specific data dictionary from observed pipeline inputs."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .schema import (
    EARLIEST_CREDIT_COLUMN,
    ISSUE_DATE_COLUMN,
    LEAKAGE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    ONE_HOT_COLUMNS,
    ORDINAL_COLUMNS,
    TARGET_COLUMN,
    TARGET_SOURCE_COLUMN,
    missing_flag_name,
)
from .transform import TransformedFeatures, resolve_loan_outcomes

DATA_DICTIONARY_COLUMNS = (
    "feature_name",
    "dtype",
    "source_column",
    "null_rate",
    "transformation_applied",
    "leakage_risk_flag",
)

_DERIVED_SOURCES = {
    "loan_to_income": "loan_amnt|annual_inc",
    "installment_to_income": "installment|annual_inc",
    "credit_history_years": f"{EARLIEST_CREDIT_COLUMN}|{ISSUE_DATE_COLUMN}",
}

_NUMERIC_TRANSFORMS = {
    "term": "parse term to months; training-median imputation",
    "int_rate": "strip optional percent sign; numeric coercion; training-median imputation",
    "revol_util": "strip optional percent sign; numeric coercion; training-median imputation",
    "emp_length": "parse employment length to years; training-median imputation",
    "loan_to_income": "safe divide loan_amnt by positive annual_inc; training-median imputation",
    "installment_to_income": (
        "safe divide installment by positive monthly income; training-median imputation"
    ),
    "credit_history_years": (
        "derive year fraction from earliest_cr_line to issue_d; training-median imputation"
    ),
}


def _raw_missing_rate(values: pd.Series) -> float:
    text = values.astype("string").str.strip().str.casefold()
    missing = values.isna() | text.isin({"", "na", "n/a", "none", "null", "nan", "nat"})
    return float(missing.mean())


def _source_for_feature(feature_name: str) -> str:
    if feature_name in _DERIVED_SOURCES:
        return _DERIVED_SOURCES[feature_name]
    if feature_name.endswith("_was_missing"):
        base = feature_name.removesuffix("_was_missing")
        return _DERIVED_SOURCES.get(base, base)
    for column in ONE_HOT_COLUMNS:
        if feature_name.startswith(f"{column}_"):
            return column
    return feature_name


def _transformation_for_feature(feature_name: str) -> str:
    if feature_name.endswith("_was_missing"):
        base = feature_name.removesuffix("_was_missing")
        return f"1 when {base} is missing or undefined before imputation"
    if feature_name in NUMERIC_FEATURE_COLUMNS:
        return _NUMERIC_TRANSFORMS.get(
            feature_name,
            "numeric coercion; training-median imputation",
        )
    if feature_name in ORDINAL_COLUMNS:
        return "fixed target-independent ordinal mapping; unknown category sentinel -1"
    for column in ONE_HOT_COLUMNS:
        if feature_name.startswith(f"{column}_"):
            return "one-hot category learned on training window; unknown categories ignored"
    return "model feature produced by the fitted Sprint 1 transformer"


def build_run_data_dictionary(
    raw_frame: pd.DataFrame,
    datasets: Mapping[str, TransformedFeatures],
) -> pd.DataFrame:
    """Return the exact feature schema and observed pre-imputation null rates.

    Numeric and engineered rates come from the transformer's missingness flags
    over all resolved temporal partitions. Categorical rates are computed from
    resolved raw rows. Leakage columns remain listed even when the allow-list
    correctly removed them during ingestion.
    """

    if not datasets:
        raise ValueError("datasets must contain at least one transformed partition")
    ordered = [datasets[name] for name in ("train", "validation", "shift") if name in datasets]
    if len(ordered) != len(datasets):
        extra_names = sorted(set(datasets) - {"train", "validation", "shift"})
        ordered.extend(datasets[name] for name in extra_names)

    feature_frames = [dataset.features for dataset in ordered]
    model_frame = pd.concat(feature_frames, ignore_index=True)
    if model_frame.empty:
        raise ValueError("transformed datasets contain no rows")
    if model_frame.columns.duplicated().any():
        raise ValueError("transformed feature names must be unique")

    resolved_raw = resolve_loan_outcomes(raw_frame).frame
    raw_rates = {
        column: _raw_missing_rate(resolved_raw[column])
        for column in resolved_raw.columns
    }
    numeric_rates = {
        feature: float(model_frame[missing_flag_name(feature)].mean())
        for feature in NUMERIC_FEATURE_COLUMNS
    }

    rows: list[dict[str, object]] = []
    for feature_name in model_frame.columns:
        source_column = _source_for_feature(str(feature_name))
        base_feature = str(feature_name).removesuffix("_was_missing")
        if base_feature in numeric_rates:
            null_rate: float | None = numeric_rates[base_feature]
        else:
            source_parts = source_column.split("|")
            source_rates = [raw_rates[item] for item in source_parts if item in raw_rates]
            null_rate = max(source_rates) if source_rates else None
        rows.append(
            {
                "feature_name": str(feature_name),
                "dtype": str(model_frame[feature_name].dtype),
                "source_column": source_column,
                "null_rate": null_rate,
                "transformation_applied": _transformation_for_feature(str(feature_name)),
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

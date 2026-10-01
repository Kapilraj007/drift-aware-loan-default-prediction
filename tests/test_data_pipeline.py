from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from drift_loan.data import (
    FeatureValidationError,
    LoanFeatureTransformer,
    SchemaValidationError,
    build_feature_store_from_csv,
    ingest_lendingclub_csv,
    load_transformer,
    read_feature_store,
    temporal_train_validation_shift_split,
    transform_features,
)
from drift_loan.data.streaming import build_streaming_feature_store


def _loan_row(
    issue_d: str,
    loan_status: str,
    *,
    row_number: int,
    **overrides: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "annual_inc": 60_000.0 + row_number * 1_000,
        "dti": 12.0 + row_number,
        "revol_util": f"{30 + row_number}%",
        "revol_bal": 5_000.0 + row_number * 100,
        "open_acc": 8 + row_number,
        "total_acc": 18 + row_number,
        "delinq_2yrs": row_number % 2,
        "inq_last_6mths": row_number % 3,
        "loan_amnt": 10_000.0 + row_number * 250,
        "term": "36 months" if row_number % 2 == 0 else "60 months",
        "int_rate": f"{9.5 + row_number / 2}%",
        "installment": 315.0 + row_number * 5,
        "grade": "ABCDEFG"[row_number % 7],
        "sub_grade": f"{'ABCDEFG'[row_number % 7]}{row_number % 5 + 1}",
        "purpose": "debt_consolidation" if row_number % 2 == 0 else "credit_card",
        "emp_length": "< 1 year" if row_number == 0 else f"{min(row_number, 10)} years",
        "home_ownership": "RENT" if row_number % 2 == 0 else "MORTGAGE",
        "earliest_cr_line": "Jan-2000",
        "issue_d": issue_d,
        "loan_status": loan_status,
        # Every one of these must be ignored, never transformed.
        "recoveries": 999.0,
        "total_pymnt": 99_999.0,
        "last_pymnt_d": "Jan-2025",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def raw_loans() -> pd.DataFrame:
    rows = [
        _loan_row("Jan-2016", "Fully Paid", row_number=0),
        _loan_row("Apr-2016", "Charged Off", row_number=1, annual_inc=None),
        _loan_row("Jul-2016", "Default", row_number=2, emp_length="10+ years"),
        _loan_row("Oct-2016", "Fully Paid", row_number=3),
        _loan_row("Jan-2017", "Fully Paid", row_number=4),
        _loan_row("Apr-2017", "Charged Off", row_number=5),
        _loan_row("Jul-2017", "Fully Paid", row_number=6),
        _loan_row("Oct-2017", "Default", row_number=7),
        _loan_row("Nov-2017", "Current", row_number=8),
    ]
    return pd.DataFrame(rows)


def test_transform_resolves_target_parses_and_excludes_leakage(raw_loans: pd.DataFrame) -> None:
    transformer = LoanFeatureTransformer()
    result = transform_features(
        raw_loans,
        transformer=transformer,
        fit=True,
        include_target=True,
    )

    assert len(result) == 8
    assert result.target is not None
    assert result.target.tolist() == [0, 1, 1, 0, 0, 1, 0, 1]
    assert not result.features.isna().any().any()
    assert not result.scaled_features.isna().any().any()
    assert result.features.columns.tolist() == result.scaled_features.columns.tolist()

    first = result.features.iloc[0]
    assert first["term"] == 36
    assert first["int_rate"] == pytest.approx(9.5)
    assert first["revol_util"] == pytest.approx(30.0)
    assert first["emp_length"] == pytest.approx(0.0)
    assert first["loan_to_income"] == pytest.approx(10_000 / 60_000)
    assert first["installment_to_income"] == pytest.approx(315 / (60_000 / 12))
    assert first["credit_history_years"] == pytest.approx(16.0, abs=0.01)
    assert first["grade"] == 0
    assert first["sub_grade"] == 0

    missing_income = result.features.iloc[1]
    assert missing_income["annual_inc_was_missing"] == 1
    assert missing_income["loan_to_income_was_missing"] == 1
    assert missing_income["installment_to_income_was_missing"] == 1
    assert result.features.iloc[2]["emp_length"] == 10

    forbidden = {
        "loan_status",
        "issue_d",
        "earliest_cr_line",
        "recoveries",
        "total_pymnt",
        "last_pymnt_d",
    }
    assert forbidden.isdisjoint(result.features.columns)


def test_encoding_is_target_independent_and_unknown_categories_are_safe(
    raw_loans: pd.DataFrame,
) -> None:
    training = raw_loans.iloc[:4].copy()
    reversed_outcomes = training.copy()
    reversed_outcomes["loan_status"] = training["loan_status"].map(
        {"Fully Paid": "Default", "Charged Off": "Fully Paid", "Default": "Fully Paid"}
    )

    left_transformer = LoanFeatureTransformer()
    right_transformer = LoanFeatureTransformer()
    left = left_transformer.fit_transform(training, include_target=True)
    right = right_transformer.fit_transform(reversed_outcomes, include_target=True)
    pd.testing.assert_series_equal(left.features["grade"], right.features["grade"])
    pd.testing.assert_series_equal(left.features["sub_grade"], right.features["sub_grade"])

    serving_row = raw_loans.iloc[[4]].copy()
    serving_row["purpose"] = "brand_new_purpose"
    serving_row["home_ownership"] = "COOPERATIVE"
    served = transform_features(serving_row, transformer=left_transformer)
    assert tuple(served.features.columns) == left_transformer.feature_names_
    assert served.target is None
    purpose_columns = [name for name in served.features if name.startswith("purpose_")]
    home_columns = [name for name in served.features if name.startswith("home_ownership_")]
    assert served.features.loc[0, purpose_columns].sum() == 0
    assert served.features.loc[0, home_columns].sum() == 0


def test_artifact_round_trip_preserves_train_serve_transform(
    raw_loans: pd.DataFrame, tmp_path: Path
) -> None:
    transformer = LoanFeatureTransformer()
    transformer.fit(raw_loans.iloc[:5], include_target=True)
    before = transformer.transform(raw_loans.iloc[[5]], include_target=False)

    artifact_dir = transformer.save_artifacts(tmp_path / "artifacts")
    loaded = load_transformer(artifact_dir)
    after = loaded.transform(raw_loans.iloc[[5]], include_target=False)

    pd.testing.assert_frame_equal(before.features, after.features)
    pd.testing.assert_frame_equal(before.scaled_features, after.scaled_features)
    metadata = json.loads((artifact_dir / "feature_metadata.json").read_text(encoding="utf-8"))
    assert metadata["schema_version"] == "1.0.0"
    assert metadata["feature_names"] == list(transformer.feature_names_)
    assert len(metadata["scaler_mean"]) == len(transformer.feature_names_)


def test_temporal_split_is_quarter_aligned_and_deterministic(raw_loans: pd.DataFrame) -> None:
    first = temporal_train_validation_shift_split(raw_loans)
    second = temporal_train_validation_shift_split(raw_loans)

    assert first.metadata.dropped_unresolved_rows == 1
    assert first.metadata.train_quarters == ("2016Q1", "2016Q2", "2016Q3", "2016Q4")
    assert first.metadata.validation_quarters == ("2017Q1",)
    assert first.metadata.shift_quarters == ("2017Q2", "2017Q3", "2017Q4")
    assert sum(first.metadata.row_counts.values()) == 8
    assert set(first.metadata.train_quarters).isdisjoint(first.metadata.validation_quarters)
    assert set(first.metadata.train_quarters).isdisjoint(first.metadata.shift_quarters)
    pd.testing.assert_frame_equal(first.train, second.train)
    pd.testing.assert_frame_equal(first.validation, second.validation)
    pd.testing.assert_frame_equal(first.shift, second.shift)


def test_csv_ingestion_detects_preamble_prunes_columns_and_chunks(
    raw_loans: pd.DataFrame, tmp_path: Path
) -> None:
    csv_path = tmp_path / "accepted.csv"
    csv_path.write_text(
        "LendingClub accepted loans export\n" + raw_loans.to_csv(index=False),
        encoding="utf-8",
    )

    result = ingest_lendingclub_csv(csv_path, chunk_size=2)
    assert len(result.frame) == len(raw_loans)
    assert result.metadata.header_rows_skipped == ((str(csv_path.resolve()), 1),)
    assert result.metadata.chunk_size == 2
    assert result.metadata.source_bytes == ((str(csv_path.resolve()), csv_path.stat().st_size),)
    assert result.metadata.source_sha256[0][0] == str(csv_path.resolve())
    assert len(result.metadata.source_sha256[0][1]) == 64
    assert set(result.metadata.ignored_leakage_columns) == {
        "last_pymnt_d",
        "recoveries",
        "total_pymnt",
    }
    assert "recoveries" not in result.frame
    assert "loan_status" in result.frame


def test_end_to_end_build_writes_partitioned_unscaled_and_scaled_views(
    raw_loans: pd.DataFrame, tmp_path: Path
) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "accepted.csv"
    raw_loans.to_csv(csv_path, index=False)
    store = tmp_path / "feature_store"
    external_artifacts = tmp_path / "preprocessor"

    build = build_feature_store_from_csv(
        csv_path,
        store,
        artifact_directory=external_artifacts,
        chunk_size=3,
    )

    assert build.feature_store_root == store.resolve()
    assert build.artifact_directory == external_artifacts.resolve()
    assert (store / "manifest.json").is_file()
    assert build.data_dictionary_path == (store / "data_dictionary.csv").resolve()
    assert build.data_dictionary_path.is_file()
    assert (store / "artifacts" / "feature_transformer.joblib").is_file()
    assert (external_artifacts / "feature_metadata.json").is_file()
    assert len(list((store / "unscaled").glob("issue_quarter=*/part-00000.parquet"))) == 8
    assert len(list((store / "scaled").glob("issue_quarter=*/part-00000.parquet"))) == 8

    unscaled = read_feature_store(store)
    scaled = read_feature_store(store, variant="scaled")
    assert len(unscaled) == len(scaled) == 8
    assert set(unscaled["target"].unique()) == {0, 1}
    assert set(unscaled["dataset_split"].unique()) == {"train", "validation", "shift"}
    assert unscaled["issue_quarter"].nunique() == 8
    assert "recoveries" not in unscaled

    scaled_train = scaled.loc[scaled["dataset_split"] == "train", list(build.feature_names)]
    assert np.allclose(scaled_train.mean(axis=0).to_numpy(), 0.0, atol=1e-10)

    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"] == {"shift": 3, "train": 4, "validation": 1}
    assert manifest["pipeline_metadata"]["fit_scope"] == "train_only"
    assert manifest["data_dictionary"] == "data_dictionary.csv"
    assert manifest["minimum_issue_quarter"] == "2016Q1"
    assert manifest["maximum_issue_quarter"] == "2017Q4"
    assert set(manifest["artifact_sha256"]) == {
        "feature_metadata.json",
        "feature_transformer.joblib",
    }
    assert all(len(digest) == 64 for digest in manifest["artifact_sha256"].values())
    assert len(manifest["data_dictionary_sha256"]) == 64
    assert manifest["feature_dtypes"]["annual_inc"] == "float64"

    dictionary = pd.read_csv(build.data_dictionary_path)
    assert dictionary.columns.tolist() == [
        "feature_name",
        "dtype",
        "source_column",
        "null_rate",
        "transformation_applied",
        "leakage_risk_flag",
    ]
    annual_income = dictionary.loc[dictionary["feature_name"] == "annual_inc"].iloc[0]
    assert annual_income["null_rate"] == pytest.approx(1 / 8)
    recoveries = dictionary.loc[dictionary["feature_name"] == "recoveries"].iloc[0]
    assert bool(recoveries["leakage_risk_flag"])
    assert dictionary["feature_name"].str.startswith("purpose_").any()


def test_streaming_build_matches_feature_store_contract(
    raw_loans: pd.DataFrame, tmp_path: Path
) -> None:
    pytest.importorskip("pyarrow")
    csv_path = tmp_path / "accepted.csv.gz"
    raw_loans.to_csv(csv_path, index=False, compression="gzip")
    store = tmp_path / "streaming_feature_store"

    build = build_streaming_feature_store(
        csv_path,
        store,
        chunk_size=3,
    )

    manifest = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    unscaled = read_feature_store(store)
    scaled = read_feature_store(store, variant="scaled")
    assert len(unscaled) == len(scaled) == 8
    assert manifest["pipeline_metadata"]["execution_mode"] == "streaming"
    assert manifest["pipeline_metadata"]["effective_chunk_size"] == 3
    assert manifest["row_counts"] == {"shift": 3, "train": 4, "validation": 1}
    assert build.ingestion.source_files == (str(csv_path.resolve()),)
    assert build.ingestion.source_bytes == ((str(csv_path.resolve()), csv_path.stat().st_size),)
    assert build.feature_names == tuple(
        column
        for column in unscaled.columns
        if column not in {"issue_d", "issue_quarter", "dataset_split", "target"}
    )


def test_clear_errors_for_missing_columns_bad_dates_and_too_few_quarters(
    raw_loans: pd.DataFrame,
) -> None:
    transformer = LoanFeatureTransformer()
    with pytest.raises(SchemaValidationError, match="missing required columns"):
        transformer.fit(raw_loans.drop(columns=["annual_inc"]), include_target=True)

    malformed = raw_loans.copy()
    malformed.loc[0, "issue_d"] = "not-a-date"
    with pytest.raises(FeatureValidationError, match="invalid examples"):
        transformer.fit(malformed, include_target=True)

    two_quarters = raw_loans.iloc[:2].copy()
    with pytest.raises(FeatureValidationError, match="at least three distinct"):
        temporal_train_validation_shift_split(two_quarters)

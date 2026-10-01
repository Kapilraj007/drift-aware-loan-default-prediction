from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from drift_loan.drift import (
    PerturbationSpec,
    ShiftMode,
    TimeWindow,
    apply_perturbations,
    load_feature_window,
    run_drift_simulation,
    slice_feature_store,
)


@pytest.fixture
def loan_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "issue_d": pd.to_datetime(
                [
                    "2017-12-31",
                    "2018-01-01",
                    "2018-01-02",
                    "2018-01-03",
                    "2018-01-04",
                    "2018-04-01",
                ]
            ),
            "issue_quarter": ["2017Q4", "2018Q1", "2018Q1", "2018Q1", "2018Q1", "2018Q2"],
            "dataset_split": ["train", "train", "validation", "validation", "test", "test"],
            "applicant_id": [f"masked-{number}" for number in range(6)],
            "int_rate": [5.0, 10.0, 15.0, 20.0, np.nan, 30.0],
            "dti": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "annual_inc": [50_000.0, 60_000.0, 70_000.0, 80_000.0, 90_000.0, 100_000.0],
            "target": pd.array([0, 0, 1, 0, 1, 1], dtype="Int8"),
        },
        index=[10, 20, 30, 40, 50, 60],
    )
    frame.attrs = {"schema_version": "test", "nested": {"owners": ["risk"]}}
    return frame


@pytest.fixture
def partitioned_store(tmp_path: Path, loan_frame: pd.DataFrame) -> Path:
    root = tmp_path / "feature_store"
    unscaled = root / "unscaled"
    scaled = root / "scaled"
    loan_frame.reset_index(drop=True).to_parquet(
        unscaled,
        partition_cols=["issue_quarter"],
        index=False,
    )
    scaled_frame = loan_frame.reset_index(drop=True).copy()
    scaled_frame["int_rate"] = -999.0
    scaled_frame.to_parquet(
        scaled,
        partition_cols=["issue_quarter"],
        index=False,
    )
    return root


@pytest.mark.parametrize(
    ("include_start", "include_end", "expected_dates"),
    [
        (True, True, ["2018-01-02", "2018-01-03", "2018-01-04"]),
        (True, False, ["2018-01-02", "2018-01-03"]),
        (False, True, ["2018-01-03", "2018-01-04"]),
        (False, False, ["2018-01-03"]),
    ],
)
def test_partitioned_store_window_boundaries(
    partitioned_store: Path,
    include_start: bool,
    include_end: bool,
    expected_dates: list[str],
) -> None:
    result = slice_feature_store(
        partitioned_store,
        window=TimeWindow(
            "2018-01-02",
            "2018-01-04",
            include_start=include_start,
            include_end=include_end,
        ),
    )

    assert result["issue_d"].dt.strftime("%Y-%m-%d").tolist() == expected_dates
    assert (result["int_rate"].dropna() != -999.0).all(), "root should default to unscaled"


def test_load_feature_window_reports_source_and_supports_open_bounds(
    partitioned_store: Path,
) -> None:
    store_slice = load_feature_window(
        partitioned_store,
        window=TimeWindow(end="2018-01-02", include_end=True),
    )

    assert len(store_slice.frame) == 3
    assert store_slice.rows_read == 6
    assert store_slice.feature_view == "unscaled"
    assert store_slice.source == (partitioned_store / "unscaled").resolve()
    assert store_slice.source_file_count == 3
    assert len(store_slice.source_files_sha256) == 64
    assert store_slice.selected_time_min == "2017-12-31T00:00:00+00:00"
    assert store_slice.selected_time_max == "2018-01-02T00:00:00+00:00"


def test_absolute_and_relative_shifts_preserve_target_metadata_and_input(
    loan_frame: pd.DataFrame,
) -> None:
    original = loan_frame.copy(deep=True)
    original.attrs = copy.deepcopy(loan_frame.attrs)

    result = apply_perturbations(
        loan_frame,
        [
            PerturbationSpec.absolute("int_rate", 5.0, clip=(0.0, 22.0)),
            PerturbationSpec.relative("dti", 0.10, clip=(None, 55.0)),
        ],
        seed=42,
        metadata_columns=("issue_d", "issue_quarter", "dataset_split", "applicant_id"),
    )

    assert_frame_equal(loan_frame, original)
    assert loan_frame.attrs == original.attrs
    assert_series_equal(result.frame["target"], original["target"])
    for column in ("issue_d", "issue_quarter", "dataset_split", "applicant_id", "annual_inc"):
        assert_series_equal(result.frame[column], original[column])

    np.testing.assert_allclose(
        result.frame["int_rate"].to_numpy(),
        np.array([10.0, 15.0, 20.0, 22.0, np.nan, 22.0]),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        result.frame["dti"].to_numpy(),
        np.array([11.0, 22.0, 33.0, 44.0, 55.0, 55.0]),
    )

    manifest = result.manifest
    assert manifest.seed == 42
    assert manifest.perturbations[0].eligible_rows == 5
    assert manifest.perturbations[0].selected_rows == 5
    assert manifest.perturbations[0].changed_rows == 5
    assert manifest.before_stats["int_rate"].mean == pytest.approx(16.0)
    assert manifest.after_stats["int_rate"].maximum == 22.0
    assert json.loads(manifest.to_json())["seed"] == 42


def test_fractional_sampling_is_deterministic_and_seeded(loan_frame: pd.DataFrame) -> None:
    frame = pd.concat([loan_frame] * 10, ignore_index=True)
    spec = PerturbationSpec.relative("int_rate", 0.15, fraction=0.35)

    first = apply_perturbations(frame, [spec], seed=2025, metadata_columns=())
    repeated = apply_perturbations(frame, [spec], seed=2025, metadata_columns=())
    another_seed = apply_perturbations(frame, [spec], seed=2026, metadata_columns=())

    assert_frame_equal(first.frame, repeated.frame)
    assert first.manifest.to_json() == repeated.manifest.to_json()
    assert not first.frame["int_rate"].equals(another_seed.frame["int_rate"])
    report = first.manifest.perturbations[0]
    assert report.eligible_rows == 50
    assert report.selected_rows == 18
    assert len(report.selected_positions_sha256) == 64


def test_result_owns_data_and_nested_attrs(loan_frame: pd.DataFrame) -> None:
    result = apply_perturbations(
        loan_frame,
        [PerturbationSpec.absolute("dti", 1.0)],
        seed=1,
    )

    result.frame.loc[10, "annual_inc"] = -1
    result.frame.attrs["nested"]["owners"].append("model-risk")
    assert loan_frame.loc[10, "annual_inc"] == 50_000.0
    assert loan_frame.attrs["nested"]["owners"] == ["risk"]


def test_non_finite_values_are_left_untouched_and_reported(loan_frame: pd.DataFrame) -> None:
    frame = loan_frame.copy(deep=True)
    frame.loc[10, "dti"] = np.inf
    frame.loc[20, "dti"] = -np.inf

    result = apply_perturbations(
        frame,
        [PerturbationSpec.absolute("dti", 2.0)],
        seed=5,
    )

    assert result.frame.loc[10, "dti"] == np.inf
    assert result.frame.loc[20, "dti"] == -np.inf
    report = result.manifest.perturbations[0]
    assert report.eligible_rows == 4
    assert report.before.non_finite_count == 2
    assert "Infinity" not in result.manifest.to_json()


def test_end_to_end_simulation_manifest_and_persistence(
    tmp_path: Path,
    partitioned_store: Path,
) -> None:
    result = run_drift_simulation(
        partitioned_store,
        window=TimeWindow("2018-01-01", "2018-04-01"),
        perturbations=[PerturbationSpec.relative("int_rate", 0.15, clip=(0.0, 100.0))],
        seed=17,
    )

    assert len(result.frame) == 4
    assert result.manifest.rows_read == 6
    assert result.manifest.rows_selected == 4
    assert result.manifest.target_column == "target"
    assert result.manifest.window == TimeWindow("2018-01-01", "2018-04-01")
    assert result.manifest.selected_time_min == "2018-01-01T00:00:00+00:00"
    assert result.manifest.selected_time_max == "2018-01-04T00:00:00+00:00"

    parquet_path, manifest_path = result.write(tmp_path / "simulation.parquet")
    persisted = pd.read_parquet(parquet_path)
    assert_frame_equal(persisted, result.frame.reset_index(drop=True))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["seed"] == 17
    assert manifest["perturbations"][0]["specification"]["mode"] == "relative"


@pytest.mark.parametrize(
    "factory,match",
    [
        (lambda: PerturbationSpec("income", 1), "feature must be one of"),
        (lambda: PerturbationSpec("dti", 1, mode="percentage"), "mode must be one of"),
        (lambda: PerturbationSpec("dti", np.nan), "shift must be finite"),
        (lambda: PerturbationSpec("dti", 1, fraction=-0.01), "fraction must be between"),
        (lambda: PerturbationSpec("dti", 1, fraction=1.01), "fraction must be between"),
        (lambda: PerturbationSpec("dti", 1, clip=(5, 4)), "clip lower bound"),
    ],
)
def test_perturbation_spec_validation(factory: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        factory()  # type: ignore[operator]


def test_simulation_input_validation(loan_frame: pd.DataFrame) -> None:
    with pytest.raises(KeyError, match="missing from frame"):
        apply_perturbations(
            loan_frame.drop(columns="dti"),
            [PerturbationSpec.absolute("dti", 1.0)],
        )

    non_numeric = loan_frame.assign(dti="unknown")
    with pytest.raises(TypeError, match="must be numeric"):
        apply_perturbations(non_numeric, [PerturbationSpec.absolute("dti", 1.0)])

    with pytest.raises(KeyError, match="protected column"):
        apply_perturbations(
            loan_frame.drop(columns="target"),
            [PerturbationSpec.absolute("dti", 1.0)],
        )

    with pytest.raises(ValueError, match="protected column"):
        apply_perturbations(
            loan_frame,
            [PerturbationSpec.absolute("dti", 1.0)],
            metadata_columns=("dti",),
        )

    with pytest.raises(ValueError, match="non-negative integer"):
        apply_perturbations(loan_frame, [], seed=-1)


def test_window_validation_and_bad_time_values(tmp_path: Path, loan_frame: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="start must be earlier"):
        TimeWindow("2019-01-01", "2018-01-01")

    bad = loan_frame.reset_index(drop=True).copy()
    bad.loc[0, "issue_d"] = pd.NaT
    path = tmp_path / "bad.parquet"
    bad.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="missing or invalid"):
        slice_feature_store(path)


def test_zero_fraction_is_an_audited_no_op(loan_frame: pd.DataFrame) -> None:
    result = apply_perturbations(
        loan_frame,
        [PerturbationSpec.absolute("dti", 10.0, fraction=0.0)],
        seed=99,
    )

    assert_frame_equal(result.frame, loan_frame)
    report = result.manifest.perturbations[0]
    assert report.selected_rows == 0
    assert report.changed_rows == 0
    assert report.before == report.after
    assert report.specification.mode is ShiftMode.ABSOLUTE

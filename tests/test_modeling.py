from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from drift_loan.cli import main
from drift_loan.modeling import (
    ModelingDataError,
    TrainingConfig,
    evaluate_binary_predictions,
    expanding_window_folds,
    load_model_bundle,
    select_validation_threshold,
    train_sprint2_models,
)

FEATURE_NAMES = ("annual_inc", "dti", "int_rate")


class FakeExplainer:
    """Pickle-safe TreeExplainer stand-in for dependency-free training tests."""

    def shap_values(self, features: pd.DataFrame, **_: object) -> np.ndarray:
        return np.zeros((len(features), features.shape[1]), dtype=np.float64)


def _fake_explainer(_: object) -> FakeExplainer:
    return FakeExplainer()


def _write_modeling_store(root: Path) -> Path:
    rows: list[dict[str, object]] = []
    quarters = (
        ("2020Q1", "train"),
        ("2020Q2", "train"),
        ("2020Q3", "train"),
        ("2020Q4", "train"),
        ("2021Q1", "train"),
        ("2021Q2", "train"),
        ("2021Q3", "validation"),
        ("2021Q4", "shift"),
    )
    for quarter_index, (quarter, split) in enumerate(quarters):
        period = pd.Period(quarter, freq="Q")
        issued = period.start_time
        for target, offset in ((0, 0.0), (1, 1.0), (0, 0.2), (1, 1.2)):
            rows.append(
                {
                    "issue_d": issued,
                    "issue_quarter": quarter,
                    "dataset_split": split,
                    "target": target,
                    "annual_inc": 50_000.0 + quarter_index * 100.0 + offset * 500.0,
                    "dti": 10.0 + target * 20.0 + offset,
                    "int_rate": 7.0 + target * 8.0 + quarter_index * 0.1,
                }
            )
    unscaled = pd.DataFrame(rows)
    scaled = unscaled.copy()
    for name in FEATURE_NAMES:
        values = scaled[name].astype(float)
        scaled[name] = (values - values.mean()) / values.std(ddof=0)

    for view_name, frame in (("unscaled", unscaled), ("scaled", scaled)):
        for quarter, partition in frame.groupby("issue_quarter", sort=True, observed=True):
            partition_dir = root / view_name / f"issue_quarter={quarter}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            partition.drop(columns="issue_quarter").to_parquet(
                partition_dir / "part-00000.parquet",
                index=False,
            )
    (root / "manifest.json").write_text(
        json.dumps({"feature_names": list(FEATURE_NAMES)}, indent=2),
        encoding="utf-8",
    )
    return root


def _logistic_factory(
    parameters: dict[str, object],
    seed: int,
    labels: np.ndarray,
) -> LogisticRegression:
    assert set(labels.tolist()) == {0, 1}
    return LogisticRegression(
        C=float(parameters.get("C", 1.0)),
        max_iter=1_000,
        random_state=seed,
    )


def _test_config() -> TrainingConfig:
    candidates = ({"C": 1.0, "max_iter": 1_000},)
    return TrainingConfig(
        random_seed=17,
        cv_splits=2,
        lightgbm_candidates=candidates,
        xgboost_candidates=candidates,
        logistic_regression_candidates=candidates,
    )


def test_expanding_window_folds_never_train_on_a_future_quarter() -> None:
    frame = pd.DataFrame(
        {
            "issue_d": pd.date_range("2020-01-01", periods=6, freq="QS"),
            "issue_quarter": ["2020Q1", "2020Q2", "2020Q3", "2020Q4", "2021Q1", "2021Q2"],
        }
    )

    folds = expanding_window_folds(frame, cv_splits=2)

    assert len(folds) == 2
    assert folds[0].train_quarters == ("2020Q1", "2020Q2")
    assert folds[0].validation_quarters == ("2020Q3", "2020Q4")
    assert folds[1].train_quarters == ("2020Q1", "2020Q2", "2020Q3", "2020Q4")
    assert folds[1].validation_quarters == ("2021Q1", "2021Q2")
    assert all(max(fold.train_quarters) < min(fold.validation_quarters) for fold in folds)


def test_metrics_and_validation_threshold_are_explicit_and_complete() -> None:
    labels = np.array([0, 0, 1, 1])
    scores = np.array([0.10, 0.35, 0.65, 0.90])

    selection = select_validation_threshold(labels, scores)
    metrics = evaluate_binary_predictions(labels, scores, threshold=selection.threshold)

    assert selection.objective == "f1"
    assert 0.0 <= selection.threshold <= 1.0
    assert metrics.accuracy == pytest.approx(1.0)
    assert metrics.roc_auc == pytest.approx(1.0)
    assert metrics.pr_auc == pytest.approx(1.0)
    assert metrics.f1 == pytest.approx(1.0)
    assert metrics.precision == pytest.approx(1.0)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.ks == pytest.approx(1.0)
    assert metrics.brier >= 0.0
    assert (metrics.true_negative, metrics.false_positive) == (2, 0)
    assert (metrics.false_negative, metrics.true_positive) == (0, 2)


def test_training_writes_loadable_primary_bundle_and_all_model_evidence(tmp_path: Path) -> None:
    store = _write_modeling_store(tmp_path / "feature_store")
    output = tmp_path / "models"
    factories = {
        "lightgbm": _logistic_factory,
        "xgboost": _logistic_factory,
        "logistic_regression": _logistic_factory,
    }

    result = train_sprint2_models(
        store,
        output,
        config=_test_config(),
        model_factories=factories,
        explainer_factory=_fake_explainer,
    )

    assert result.metadata_path.is_file()
    assert result.feature_schema_path.is_file()
    assert result.metrics_path.is_file()
    assert result.detector_path.is_file()
    assert result.explainer_path.is_file()
    assert set(result.model_paths) == {"lightgbm", "xgboost", "logistic_regression"}
    assert all(path.is_file() for path in result.model_paths.values())
    assert result.model_paths["lightgbm"].name == "model.joblib"
    assert set(result.evaluations) == {"lightgbm", "xgboost", "logistic_regression"}
    assert all(
        evaluation.threshold_selection.validation_metrics.threshold
        == evaluation.threshold_selection.threshold
        for evaluation in result.evaluations.values()
    )
    assert all(
        evaluation.shift_metrics.threshold == evaluation.threshold_selection.threshold
        for evaluation in result.evaluations.values()
    )

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["threshold_source"] == "validation_only_f1"
    assert metadata["prediction_threshold"] == metadata["threshold"]
    assert metadata["model_artifact"] == "model.joblib"
    assert metadata["model_version"] == result.model_version
    assert metadata["training_window"]["split"] == "train"
    assert metadata["validation_window"]["split"] == "validation"
    assert metadata["shift_window"]["split"] == "shift"
    assert metadata["adwin_detector_artifact"] == "adwin_detector.joblib"
    assert metadata["shap_explainer_artifact"] == "shap_explainer.joblib"

    bundle = load_model_bundle(output)
    sample = pd.DataFrame(
        {
            "int_rate": [7.0, 15.0],
            "annual_inc": [50_000.0, 51_000.0],
            "dti": [10.0, 31.0],
        }
    )
    probabilities = bundle.predict_proba_features(sample)
    assert probabilities.shape == (2,)
    assert np.all((probabilities >= 0.0) & (probabilities <= 1.0))
    assert bundle.predict_features(sample).shape == (2,)
    assert bundle.explain_features(sample).shape == (2, 3)
    assert bundle.model_version == result.model_version
    assert bundle.metadata["model_version"] == result.model_version

    with pytest.raises(ModelingDataError, match="outside the persisted feature schema"):
        bundle.predict_proba_features(sample.assign(extra=1.0))
    with pytest.raises(ModelingDataError, match="missing"):
        bundle.predict_proba_features(sample.drop(columns="dti"))


def test_training_refuses_to_overwrite_an_artifact_directory(tmp_path: Path) -> None:
    store = _write_modeling_store(tmp_path / "feature_store")
    output = tmp_path / "models"
    factories = {name: _logistic_factory for name in ("lightgbm", "xgboost", "logistic_regression")}
    train_sprint2_models(
        store,
        output,
        config=_test_config(),
        model_factories=factories,
        explainer_factory=_fake_explainer,
    )

    with pytest.raises(Exception, match="already exists"):
        train_sprint2_models(
            store,
            output,
            config=_test_config(),
            model_factories=factories,
            explainer_factory=_fake_explainer,
        )


def test_train_model_cli_dispatches_the_expected_temporal_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    class StubResult:
        def to_dict(self) -> dict[str, str]:
            return {"status": "ok"}

    def fake_train(
        feature_store: Path,
        output_dir: Path,
        *,
        config: TrainingConfig,
        overwrite: bool,
    ) -> StubResult:
        observed.update(
            {
                "feature_store": feature_store,
                "output_dir": output_dir,
                "config": config,
                "overwrite": overwrite,
            }
        )
        return StubResult()

    monkeypatch.setattr("drift_loan.cli.train_sprint2_models", fake_train)
    exit_code = main(
        [
            "train-model",
            "--feature-store",
            str(tmp_path / "feature_store"),
            "--model-directory",
            str(tmp_path / "models"),
            "--seed",
            "19",
            "--cv-splits",
            "2",
            "--overwrite",
        ]
    )

    assert exit_code == 0
    assert observed["feature_store"] == tmp_path / "feature_store"
    assert observed["output_dir"] == tmp_path / "models"
    assert observed["overwrite"] is True
    config = observed["config"]
    assert isinstance(config, TrainingConfig)
    assert config.random_seed == 19
    assert config.cv_splits == 2
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}

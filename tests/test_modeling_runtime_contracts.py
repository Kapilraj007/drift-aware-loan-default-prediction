"""Focused contracts for model-family adapters used by the serving workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

import drift_loan.modeling.estimators as estimators_module
import drift_loan.modeling.explanations as explanations_module
import drift_loan.modeling.monitoring as monitoring_module
from drift_loan.modeling import (
    ModelingDataError,
    ModelingDependencyError,
    calibrate_adwin_detector,
    create_estimator,
    create_tree_explainer,
    explain_transformed_features,
    positive_class_probabilities,
)
from drift_loan.modeling.estimators import (
    create_lightgbm_estimator,
    create_logistic_regression_estimator,
    create_xgboost_estimator,
)


class CaptureClassifier:
    """Dependency-free classifier constructor that retains factory options."""

    def __init__(self, **options: object) -> None:
        self.options = options


class Predictor:
    """Small probability estimator double with explicit class ordering."""

    def __init__(self, probabilities: object, classes: object) -> None:
        self.probabilities = probabilities
        self.classes_ = classes

    def predict_proba(self, _: object) -> object:
        return self.probabilities


class RaisingPredictor:
    def predict_proba(self, _: object) -> object:
        raise ValueError("backend prediction failed")


class CaptureADWIN:
    def __init__(self, *, delta: float) -> None:
        self.delta = delta
        self.observations: list[float] = []

    def update(self, value: float) -> None:
        self.observations.append(value)


def test_estimator_factories_preserve_defaults_and_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = {
        "lightgbm": SimpleNamespace(LGBMClassifier=CaptureClassifier),
        "xgboost": SimpleNamespace(XGBClassifier=CaptureClassifier),
    }
    monkeypatch.setattr(estimators_module.importlib, "import_module", modules.__getitem__)
    labels = np.array([0, 0, 1])

    lightgbm = create_lightgbm_estimator({"n_estimators": 7}, random_seed=19, labels=labels)
    assert isinstance(lightgbm, CaptureClassifier)
    assert lightgbm.options["objective"] == "binary"
    assert lightgbm.options["n_estimators"] == 7
    assert lightgbm.options["class_weight"] == "balanced"
    assert lightgbm.options["random_state"] == 19
    assert lightgbm.options["deterministic"] is True

    xgboost = create_xgboost_estimator({"max_depth": 3}, random_seed=23, labels=labels)
    assert isinstance(xgboost, CaptureClassifier)
    assert xgboost.options["objective"] == "binary:logistic"
    assert xgboost.options["max_depth"] == 3
    assert xgboost.options["scale_pos_weight"] == pytest.approx(2.0)
    assert xgboost.options["random_state"] == 23

    logistic = create_logistic_regression_estimator({"C": 0.4}, random_seed=29, labels=labels)
    assert isinstance(logistic, LogisticRegression)
    assert logistic.C == pytest.approx(0.4)
    assert logistic.class_weight == "balanced"
    assert logistic.random_state == 29


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        ([], "must not be empty"),
        (["not-a-label", 1], "binary 0/1"),
        ([0, 0], "both binary classes"),
    ],
)
def test_estimator_label_contract_rejects_invalid_training_targets(
    labels: object,
    message: str,
) -> None:
    with pytest.raises(ModelingDataError, match=message):
        create_estimator(
            "logistic_regression",
            {},
            random_seed=1,
            labels=np.asarray(labels),
        )


def test_estimator_dispatches_custom_factory_and_rejects_unknown_names() -> None:
    observed: dict[str, Any] = {}

    def factory(parameters: object, seed: int, labels: np.ndarray) -> str:
        observed.update(parameters=dict(parameters), seed=seed, labels=labels.tolist())
        return "custom-estimator"

    estimator = create_estimator(
        "lightgbm",
        {"num_leaves": 9},
        random_seed=31,
        labels=np.array([0, 1]),
        factories={"lightgbm": factory},
    )
    assert estimator == "custom-estimator"
    assert observed == {"parameters": {"num_leaves": 9}, "seed": 31, "labels": [0, 1]}

    default_estimator = create_estimator(
        "logistic_regression",
        {"max_iter": 77},
        random_seed=37,
        labels=np.array([0, 1]),
    )
    assert isinstance(default_estimator, LogisticRegression)
    assert default_estimator.max_iter == 77

    with pytest.raises(ModelingDataError, match="model_name must be one of"):
        create_estimator(
            "unsupported",
            {},
            random_seed=1,
            labels=np.array([0, 1]),
        )


def test_optional_estimator_dependency_failure_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_: str) -> object:
        raise ImportError("not installed")

    monkeypatch.setattr(estimators_module.importlib, "import_module", missing)
    with pytest.raises(ModelingDependencyError, match="lightgbm is required"):
        create_lightgbm_estimator({}, random_seed=1, labels=np.array([0, 1]))


def test_positive_class_probabilities_honors_label_order_and_binary_fallback() -> None:
    ordered = Predictor([[0.70, 0.30], [0.20, 0.80]], classes=[1, 0])
    fallback = Predictor([[0.70, 0.30], [0.20, 0.80]], classes=[])

    np.testing.assert_allclose(positive_class_probabilities(ordered, object()), [0.70, 0.20])
    np.testing.assert_allclose(positive_class_probabilities(fallback, object()), [0.30, 0.80])


def test_positive_class_probability_contract_rejects_invalid_estimators() -> None:
    with pytest.raises(ModelingDataError, match="does not provide predict_proba"):
        positive_class_probabilities(object(), object())
    with pytest.raises(ModelingDataError, match="failed to produce probabilities"):
        positive_class_probabilities(RaisingPredictor(), object())
    with pytest.raises(ModelingDataError, match="non-empty 2D"):
        positive_class_probabilities(Predictor([0.2, 0.8], [0, 1]), object())
    with pytest.raises(ModelingDataError, match="uniquely identifiable positive class"):
        positive_class_probabilities(Predictor([[0.2, 0.3, 0.5]], [0, 2, 3]), object())
    with pytest.raises(ModelingDataError, match="index exceeds"):
        positive_class_probabilities(Predictor([[0.2, 0.8]], [0, 0, 1]), object())
    with pytest.raises(ModelingDataError, match="non-finite or out-of-range"):
        positive_class_probabilities(Predictor([[0.2, 1.2]], [0, 1]), object())


def test_tree_explainer_maps_dependency_and_constructor_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = object()
    monkeypatch.setattr(
        explanations_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(TreeExplainer=lambda model: expected),
    )
    assert create_tree_explainer(object()) is expected

    def invalid_constructor(_: object) -> object:
        raise ValueError("unsupported model")

    monkeypatch.setattr(
        explanations_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(TreeExplainer=invalid_constructor),
    )
    with pytest.raises(ModelingDataError, match="Unable to create"):
        create_tree_explainer(object())

    def missing(_: str) -> object:
        raise ImportError("not installed")

    monkeypatch.setattr(explanations_module.importlib, "import_module", missing)
    with pytest.raises(ModelingDependencyError, match="shap is required"):
        create_tree_explainer(object())


def test_explanations_normalize_supported_binary_shap_output_shapes() -> None:
    features = pd.DataFrame({"income": [50_000.0, 60_000.0], "dti": [10.0, 20.0]})
    list_explainer = SimpleNamespace(
        shap_values=lambda _features, **_: [
            np.zeros((2, 2)),
            np.array([[1.0, 2.0], [3.0, 4.0]]),
        ]
    )
    tensor_explainer = SimpleNamespace(
        shap_values=lambda _features, **_: np.array(
            [[[0.0, 1.0], [2.0, 3.0]], [[4.0, 5.0], [6.0, 7.0]]]
        )
    )

    np.testing.assert_allclose(
        explain_transformed_features(list_explainer, features),
        [[1.0, 2.0], [3.0, 4.0]],
    )
    np.testing.assert_allclose(
        explain_transformed_features(tensor_explainer, features),
        [[1.0, 3.0], [5.0, 7.0]],
    )

    class NoKeywordExplainer:
        def shap_values(self, _: pd.DataFrame) -> np.ndarray:
            return np.ones((2, 2))

    np.testing.assert_allclose(
        explain_transformed_features(NoKeywordExplainer(), features),
        np.ones((2, 2)),
    )


def test_explanation_contract_rejects_invalid_feature_and_explainer_outputs() -> None:
    features = pd.DataFrame({"income": [50_000.0], "dti": [10.0]})
    valid_values = np.zeros((1, 2))
    valid_explainer = SimpleNamespace(shap_values=lambda _features, **_: valid_values)
    with pytest.raises(ModelingDataError, match="non-empty pandas DataFrame"):
        explain_transformed_features(valid_explainer, pd.DataFrame())
    with pytest.raises(ModelingDataError, match="does not provide shap_values"):
        explain_transformed_features(object(), features)
    with pytest.raises(ModelingDataError, match="exactly negative and positive-class"):
        explain_transformed_features(
            SimpleNamespace(shap_values=lambda _features, **_: [valid_values]),
            features,
        )
    with pytest.raises(ModelingDataError, match="do not match"):
        explain_transformed_features(
            SimpleNamespace(shap_values=lambda _features, **_: np.zeros((1, 1))),
            features,
        )
    with pytest.raises(ModelingDataError, match="non-finite"):
        explain_transformed_features(
            SimpleNamespace(shap_values=lambda _features, **_: np.array([[np.nan, 0.0]])),
            features,
        )

    def fails(_: pd.DataFrame, **__: object) -> object:
        raise ValueError("explainer failed")

    with pytest.raises(ModelingDataError, match="SHAP explanation failed"):
        explain_transformed_features(SimpleNamespace(shap_values=fails), features)


def test_adwin_calibration_replays_valid_scores_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitoring_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(ADWIN=CaptureADWIN),
    )

    detector = calibrate_adwin_detector([0.1, 0.3, 0.8], delta=np.float64(0.05))

    assert isinstance(detector, CaptureADWIN)
    assert detector.delta == pytest.approx(0.05)
    assert detector.observations == [0.1, 0.3, 0.8]


def test_adwin_calibration_rejects_invalid_inputs_and_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ModelingDataError, match="delta"):
        calibrate_adwin_detector([0.1], delta="not-a-number")  # type: ignore[arg-type]
    with pytest.raises(ModelingDataError, match="delta"):
        calibrate_adwin_detector([0.1], delta=0.0)
    with pytest.raises(ModelingDataError, match="must be numeric"):
        calibrate_adwin_detector(["bad-score"])
    with pytest.raises(ModelingDataError, match="non-empty and finite"):
        calibrate_adwin_detector([])
    with pytest.raises(ModelingDataError, match="probabilities"):
        calibrate_adwin_detector([1.1])

    def missing(_: str) -> object:
        raise ImportError("not installed")

    monkeypatch.setattr(monitoring_module.importlib, "import_module", missing)
    with pytest.raises(ModelingDependencyError, match="river is required"):
        calibrate_adwin_detector([0.1])

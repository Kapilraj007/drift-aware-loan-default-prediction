"""Focused contracts for the synthetic showcase preparation path."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.db.seed import _demo_features
from backend.app.models.schemas import LoanApplicationFeatures
from backend.app.services.drift_service import DriftService
from drift_loan.modeling import ModelingDataError, TrainingConfig
from scripts.generate_demo_data import generate_rows


def test_demo_generator_guarantees_both_resolved_classes_per_quarter() -> None:
    rows = generate_rows(400, seed=20260926)
    statuses: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        statuses[str(row["issue_d"])].add(str(row["loan_status"]))

    assert len(statuses) == 20
    for observed in statuses.values():
        assert "Fully Paid" in observed
        assert observed.intersection({"Charged Off", "Default"})


def test_training_config_accepts_metadata_only_synthetic_marker() -> None:
    assert TrainingConfig(synthetic_demo=True).synthetic_demo is True
    with pytest.raises(ModelingDataError, match="synthetic_demo must be a boolean"):
        TrainingConfig(synthetic_demo="yes")  # type: ignore[arg-type]


def test_committed_sample_application_is_utf8_without_bom() -> None:
    path = Path("samples/sample-application.json")
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    payload = json.loads(raw.decode("utf-8"))
    assert payload["issue_d"] == "Jan-2018"
    assert payload["term"] == "36 months"


def test_all_seeded_demo_applications_match_the_strict_serving_schema() -> None:
    validated = [
        LoanApplicationFeatures.model_validate(_demo_features(index))
        for index in range(50)
    ]
    assert len(validated) == 50
    assert all(application.issue_d for application in validated)


def test_nullable_transformer_missing_value_forms_are_accepted() -> None:
    payload = _demo_features(0)
    payload["emp_length"] = "n/a"
    payload["earliest_cr_line"] = ""
    validated = LoanApplicationFeatures.model_validate(payload)
    assert validated.emp_length is None
    assert validated.earliest_cr_line is None


def test_drift_rehydration_replays_scores_and_restores_feature_state() -> None:
    settings = Settings(
        database_url="postgresql://demo:demo@example.invalid/demo?sslmode=require",
        direct_database_url="postgresql://demo:demo@example.invalid/demo?sslmode=require",
        jwt_secret_key="unit-test-secret-that-is-longer-than-32-chars",
    )
    service = DriftService(settings)
    snapshot = service.rehydrate(
        [0.2, 0.8],
        {
            "score_stream_count": 42,
            "latest_score": 0.8,
            "adwin_change_detected": False,
            "updated_at": "2026-10-02T10:00:00+00:00",
            "feature_results": [
                {
                    "feature": "dti",
                    "statistic": 1.0,
                    "p_value": 0.0001,
                    "drift_detected": True,
                    "reference_count": 100,
                    "current_count": 100,
                }
            ],
        },
    )
    assert snapshot.status == "drift_detected"
    assert snapshot.score_stream_count == 42
    assert snapshot.latest_score == pytest.approx(0.8)
    assert snapshot.feature_results[0].feature == "dti"

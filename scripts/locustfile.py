"""Authenticated inference load scenario for a local or staging-like API.

The scenario deliberately uses the direct prediction contract so it exercises
the real transformer, model, SHAP explanation path, and prediction endpoint.
It still writes prediction/audit records and updates the in-memory drift
detector, so it must only run against an isolated test environment.
"""

from __future__ import annotations

import os
from typing import Any

from locust import HttpUser, between, task

DEFAULT_FEATURES: dict[str, Any] = {
    "annual_inc": 75_000.0,
    "dti": 16.5,
    "revol_util": "38%",
    "revol_bal": 8_200.0,
    "open_acc": 10.0,
    "total_acc": 25.0,
    "delinq_2yrs": 0.0,
    "inq_last_6mths": 1.0,
    "loan_amnt": 12_000.0,
    "term": "36 months",
    "int_rate": "11.2%",
    "installment": 394.0,
    "grade": "B",
    "sub_grade": "B3",
    "purpose": "debt_consolidation",
    "emp_length": "5 years",
    "home_ownership": "RENT",
    "earliest_cr_line": "Jan-2006",
    "issue_d": "Jan-2019",
}


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set before starting the load test")
    return value


class InferenceUser(HttpUser):
    """A loan officer who signs in once and repeatedly requests a score."""

    host = os.getenv("LOAD_TEST_BASE_URL", "http://localhost:8000")
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        username = _required_environment("LOAD_TEST_USERNAME")
        password = _required_environment("LOAD_TEST_PASSWORD")
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            name="POST /api/v1/auth/login (setup)",
        )
        if response.status_code != 200:
            raise RuntimeError(f"load-test authentication failed with HTTP {response.status_code}")

        try:
            access_token = response.json().get("access_token")
        except ValueError as exc:
            raise RuntimeError("load-test authentication returned invalid JSON") from exc
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError("load-test authentication response did not include an access token")

        self.client.headers.update({"Authorization": f"Bearer {access_token}"})

    @task
    def request_inference(self) -> None:
        with self.client.post(
            "/api/v1/predictions",
            json={"features": DEFAULT_FEATURES},
            name="POST /api/v1/predictions",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"expected HTTP 201, received HTTP {response.status_code}")
                return

            try:
                payload = response.json()
            except ValueError:
                response.failure("prediction response was not valid JSON")
                return

            score = payload.get("score") if isinstance(payload, dict) else None
            if isinstance(score, bool) or not isinstance(score, int | float):
                response.failure("prediction response did not include a numeric score")
                return
            if not 0.0 <= score <= 1.0:
                response.failure("prediction score was outside the expected [0, 1] range")
                return
            if not isinstance(payload.get("risk_flag"), bool):
                response.failure("prediction response did not include a boolean risk_flag")
                return

            response.success()

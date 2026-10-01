"""Pydantic API contracts for the Sprint 2 decision-support backend."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.security import UserRole


class ApiModel(BaseModel):
    """Shared response settings for Pydantic v2."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class UserRegisterRequest(ApiModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: UserRole = UserRole.LOAN_OFFICER


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class UserResponse(ApiModel):
    id: str
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime


class LoanApplicationFeatures(ApiModel):
    """The raw, pre-origination fields required by the frozen transformer.

    Nullable numeric fields intentionally remain valid: the shared Sprint 1
    transformer supplies training-derived medians and missingness indicators.
    Every field must nevertheless be present so requests cannot silently omit a
    predictor.
    """

    annual_inc: float | None
    dti: float | None
    revol_util: float | str | None
    revol_bal: float | None
    open_acc: float | None
    total_acc: float | None
    delinq_2yrs: float | None
    inq_last_6mths: float | None
    loan_amnt: float | None
    term: float | str | None
    int_rate: float | str | None
    installment: float | None
    grade: str | None
    sub_grade: str | None
    purpose: str | None
    emp_length: float | str | None
    home_ownership: str | None
    earliest_cr_line: str | None
    issue_d: str

    def as_raw_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class ApplicationCreateRequest(ApiModel):
    external_reference: str | None = Field(default=None, max_length=128)
    features: LoanApplicationFeatures


class ApplicationResponse(ApiModel):
    id: str
    external_reference: str | None
    features: LoanApplicationFeatures
    created_by_id: str
    created_at: datetime


class DirectPredictionRequest(ApiModel):
    application_id: str | None = None
    features: LoanApplicationFeatures | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> DirectPredictionRequest:
        if (self.application_id is None) == (self.features is None):
            raise ValueError("Provide exactly one of application_id or features")
        return self


class FeatureContribution(ApiModel):
    feature: str
    display_name: str
    contribution: float
    direction: str
    feature_value: float | int | str | None = None


class ExplanationResponse(ApiModel):
    available: bool
    narrative: str
    top_features: list[FeatureContribution] = Field(default_factory=list)


class ExplanationVariant(StrEnum):
    SCORE_ONLY = "score_only"
    EXPLANATION_SHOWN = "explanation_shown"


class ExplanationAssignmentResponse(ApiModel):
    id: str
    variant: ExplanationVariant
    created_at: datetime


class ExplanationExposureCreateRequest(ApiModel):
    prediction_id: str


class ExplanationExposureResponse(ApiModel):
    id: str
    prediction_id: str
    assignment_id: str
    variant: ExplanationVariant
    explanation_shown: bool
    created_at: datetime


class DriftStatusResponse(ApiModel):
    status: str
    score_stream_count: int
    latest_score: float | None = None
    adwin_change_detected: bool = False
    feature_drift_count: int = 0
    updated_at: datetime | None = None
    feature_results: list[dict[str, Any]] = Field(default_factory=list)


class MonitoringSnapshotSource(StrEnum):
    SCORE_OBSERVATION = "score_observation"
    FEATURE_DRIFT = "feature_drift"


class MonitoringHistorySnapshotResponse(ApiModel):
    id: str
    source: MonitoringSnapshotSource
    snapshot: DriftStatusResponse
    created_at: datetime


class MonitoringHistoryResponse(ApiModel):
    snapshots: list[MonitoringHistorySnapshotResponse] = Field(default_factory=list)


class PredictionResponse(ApiModel):
    id: str
    application_id: str | None
    model_version: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(gt=0.0, lt=1.0)
    risk_flag: bool
    explanation: ExplanationResponse
    study_variant: ExplanationVariant | None = None
    detector_state: DriftStatusResponse
    created_at: datetime


class OfficerDecision(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"
    ESCALATE = "escalate"


class FeedbackCreateRequest(ApiModel):
    prediction_id: str
    decision: OfficerDecision
    agreed_with_model: bool | None = None
    note: str | None = Field(default=None, max_length=4_000)


class FeedbackResponse(ApiModel):
    id: str
    prediction_id: str
    officer_id: str
    decision: OfficerDecision
    agreed_with_model: bool | None
    note: str | None
    detector_state: DriftStatusResponse
    created_at: datetime


class FeatureDriftRequest(ApiModel):
    """Two in-memory cohorts for analyst-triggered KS feature checks."""

    reference_rows: list[dict[str, Any]] = Field(min_length=2, max_length=100_000)
    current_rows: list[dict[str, Any]] = Field(min_length=2, max_length=100_000)
    alpha: float = Field(default=0.01, gt=0.0, lt=1.0)


class FeatureDriftResponse(DriftStatusResponse):
    evaluated_features: int


class RetrainingTicketStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"


class RetrainingTicketCreateRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=4_000)
    human_review_confirmed: Literal[True]


class RetrainingTicketReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RetrainingTicketReviewRequest(ApiModel):
    decision: RetrainingTicketReviewDecision
    note: str | None = Field(default=None, max_length=4_000)


class RetrainingTicketResponse(ApiModel):
    id: str
    monitoring_snapshot_id: str
    reason: str
    human_review_confirmed: bool
    status: RetrainingTicketStatus
    requested_by_id: str
    reviewed_by_id: str | None
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ModelMetadataResponse(ApiModel):
    model_version: str
    feature_view: str
    prediction_threshold: float
    feature_count: int
    feature_schema_sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingRunsResponse(ApiModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)

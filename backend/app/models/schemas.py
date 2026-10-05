"""Typed API contracts for authentication, review, monitoring, and administration."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.rbac import UserRole
from ..core.security import validate_password_policy


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


def _valid_password(value: str) -> str:
    try:
        return validate_password_policy(value)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str

    _validate_new_password = field_validator("new_password")(_valid_password)


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class UserCreateRequest(ApiModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str
    role: UserRole = UserRole.LOAN_OFFICER
    email: str | None = Field(default=None, max_length=320)
    full_name: str | None = Field(default=None, max_length=200)
    must_change_password: bool = True

    _validate_password = field_validator("password")(_valid_password)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("Enter a valid email address")
        return normalized


class UserUpdateRequest(ApiModel):
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return UserCreateRequest.validate_email(value)


class UserResponse(ApiModel):
    id: str
    username: str
    role: UserRole
    permissions: list[str] = Field(default_factory=list)
    email: str | None
    full_name: str | None
    must_change_password: bool
    last_login_at: datetime | None
    is_active: bool
    created_at: datetime


class UserListResponse(ApiModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class ResetPasswordResponse(ApiModel):
    temporary_password: str
    must_change_password: Literal[True] = True


class RoleResponse(ApiModel):
    id: str
    name: UserRole
    description: str
    is_system: bool
    permissions: list[str]


class AuditEventResponse(ApiModel):
    id: str
    actor_user_id: str | None
    actor_username: str | None = None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any]
    ip: str | None
    created_at: datetime


class AuditEventListResponse(ApiModel):
    items: list[AuditEventResponse]
    total: int
    limit: int
    offset: int


_DATE_FORMATS = (
    "%b-%Y",
    "%b-%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)
PURPOSE_VALUES = (
    "car",
    "credit_card",
    "debt_consolidation",
    "educational",
    "home_improvement",
    "house",
    "major_purchase",
    "medical",
    "moving",
    "other",
    "renewable_energy",
    "small_business",
    "vacation",
    "wedding",
)
HOME_OWNERSHIP_VALUES = ("ANY", "MORTGAGE", "NONE", "OTHER", "OWN", "RENT")


def _parse_date(value: str, field: str) -> date:
    normalized = value.strip()
    for format_string in _DATE_FORMATS:
        try:
            return datetime.strptime(normalized, format_string).date()
        except ValueError:
            continue
    raise ValueError(
        f"{field} must use Mon-YYYY, Mon-YY, YYYY-MM-DD, YYYY/MM/DD, or ISO date-time"
    )


def _percent_number(value: float | str | None, field: str) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a number or percentage") from exc
    if not 0 <= number <= 1_000:
        raise ValueError(f"{field} must be between 0 and 1000")
    return value


class LoanApplicationFeatures(ApiModel):
    """Strict serving schema aligned with the frozen LendingClub transformer."""

    annual_inc: float | None = Field(ge=0, le=1_000_000_000)
    dti: float | None = Field(ge=0, le=1_000)
    revol_util: float | str | None
    revol_bal: float | None = Field(ge=0, le=1_000_000_000)
    open_acc: float | None = Field(ge=0, le=10_000)
    total_acc: float | None = Field(ge=0, le=10_000)
    delinq_2yrs: float | None = Field(ge=0, le=10_000)
    inq_last_6mths: float | None = Field(ge=0, le=10_000)
    loan_amnt: float | None = Field(gt=0, le=10_000_000)
    term: int | str | None
    int_rate: float | str | None
    installment: float | None = Field(ge=0, le=10_000_000)
    grade: str | None
    sub_grade: str | None
    purpose: str | None
    emp_length: float | str | None
    home_ownership: str | None
    earliest_cr_line: str | None
    issue_d: str

    @field_validator("term", mode="before")
    @classmethod
    def validate_term(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"36", "36.0", "36 month", "36 months"}:
            return 36 if not isinstance(value, str) else value
        if normalized in {"60", "60.0", "60 month", "60 months"}:
            return 60 if not isinstance(value, str) else value
        raise ValueError("term must be 36, 60, '36 months', or '60 months'")

    @field_validator("emp_length", mode="before")
    @classmethod
    def validate_emp_length(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"", "n/a", "na", "none", "null"}:
            return None
        if normalized in {"< 1 year", "<1 year", "less than 1 year"}:
            return value
        suffix = normalized.removesuffix("+").replace("+ ", " ")
        for ending in (" years", " year"):
            if suffix.endswith(ending):
                suffix = suffix[: -len(ending)]
                break
        try:
            years = float(suffix.replace("+", "").strip())
        except ValueError as exc:
            raise ValueError("emp_length must be a number of years") from exc
        if not 0 <= years <= 100:
            raise ValueError("emp_length must be between 0 and 100 years")
        return value

    @field_validator("int_rate", mode="before")
    @classmethod
    def validate_int_rate(cls, value: object) -> object:
        result = _percent_number(value, "int_rate")  # type: ignore[arg-type]
        if result is not None:
            numeric = float(str(result).strip().removesuffix("%"))
            if numeric > 100:
                raise ValueError("int_rate must be between 0 and 100")
        return result

    @field_validator("revol_util", mode="before")
    @classmethod
    def validate_revol_util(cls, value: object) -> object:
        return _percent_number(value, "revol_util")  # type: ignore[arg-type]

    @field_validator("grade", mode="before")
    @classmethod
    def validate_grade(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if normalized not in set("ABCDEFG"):
            raise ValueError("grade must be A through G")
        return normalized

    @field_validator("sub_grade", mode="before")
    @classmethod
    def validate_sub_grade(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if len(normalized) != 2 or normalized[0] not in "ABCDEFG" or normalized[1] not in "12345":
            raise ValueError("sub_grade must be A1 through G5")
        return normalized

    @field_validator("purpose", mode="before")
    @classmethod
    def validate_purpose(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().lower().replace(" ", "_")
        if normalized not in PURPOSE_VALUES:
            raise ValueError("purpose is not an allowed LendingClub purpose")
        return normalized

    @field_validator("home_ownership", mode="before")
    @classmethod
    def validate_home_ownership(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper().replace(" ", "_")
        if normalized not in HOME_OWNERSHIP_VALUES:
            raise ValueError("home_ownership is not allowed")
        return normalized

    @field_validator("issue_d", "earliest_cr_line")
    @classmethod
    def validate_dates(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            if info.field_name == "issue_d":
                raise ValueError("issue_d is required")
            return None
        if info.field_name == "earliest_cr_line" and value.strip().lower() in {
            "",
            "n/a",
            "na",
            "none",
            "null",
        }:
            return None
        _parse_date(value, info.field_name)
        return value.strip()

    @model_validator(mode="after")
    def validate_date_order(self) -> LoanApplicationFeatures:
        if self.earliest_cr_line is not None:
            earliest = _parse_date(self.earliest_cr_line, "earliest_cr_line")
            issued = _parse_date(self.issue_d, "issue_d")
            if earliest > issued:
                raise ValueError("earliest_cr_line must not be after issue_d")
        if self.grade and self.sub_grade and self.grade != self.sub_grade[0]:
            raise ValueError("sub_grade must belong to grade")
        return self

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


class ApplicationStatus(StrEnum):
    UNSCORED = "unscored"
    SCORED = "scored"
    DECIDED = "decided"
    ESCALATED = "escalated"


class ApplicationListItemResponse(ApplicationResponse):
    status: ApplicationStatus
    latest_prediction_id: str | None = None
    score: float | None = None
    risk_flag: bool | None = None
    current_decision: str | None = None


class ApplicationListResponse(ApiModel):
    items: list[ApplicationListItemResponse]
    total: int
    limit: int
    offset: int


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
    requested_by_id: str
    model_version: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(gt=0.0, lt=1.0)
    risk_flag: bool
    explanation: ExplanationResponse
    study_variant: ExplanationVariant | None = None
    detector_state: DriftStatusResponse
    created_at: datetime


class PredictionListResponse(ApiModel):
    items: list[PredictionResponse]
    total: int
    limit: int
    offset: int


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
    version: int
    amends_feedback_id: str | None
    is_current: bool
    decision: OfficerDecision
    agreed_with_model: bool | None
    note: str | None
    detector_state: DriftStatusResponse
    created_at: datetime


class FeedbackListResponse(ApiModel):
    items: list[FeedbackResponse]
    total: int
    limit: int
    offset: int


class ApplicationReviewResponse(ApiModel):
    application: ApplicationResponse
    latest_prediction: PredictionResponse | None
    feedback_history: list[FeedbackResponse]
    current_feedback: FeedbackResponse | None


class FeatureDriftRequest(ApiModel):
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
    synthetic_demo: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingRunsResponse(ApiModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)
    synthetic_demo: bool = False


class ReferenceFieldResponse(ApiModel):
    name: str
    label: str
    type: str
    group: str
    required: bool
    nullable: bool
    allowed_values: list[str | int] | None = None
    format: str | None = None
    help_text: str
    description: str


class ApplicationSchemaResponse(ApiModel):
    fields: list[ReferenceFieldResponse]


class ScoreDistributionBin(ApiModel):
    minimum: float
    maximum: float
    count: int


class DashboardSummaryResponse(ApiModel):
    applications: int
    scored: int
    decided: int
    pending: int
    risk_flag_rate: float | None
    decision_mix: dict[str, int]
    agreement_rate: float | None
    override_rate: float | None
    latest_drift_status: str
    open_tickets: int
    score_distribution: list[ScoreDistributionBin]
    recent_applications: list[ApplicationListItemResponse]


class ExperimentArmSummary(ApiModel):
    variant: ExplanationVariant
    exposures: int
    decisions: int
    agreement_rate: float | None
    override_rate: float | None


class ExperimentSummaryResponse(ApiModel):
    arms: list[ExperimentArmSummary]
    note: str = "Descriptive counts only; no statistical significance is claimed."

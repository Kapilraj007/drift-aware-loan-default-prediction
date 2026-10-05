"""Stable permission catalogue and the three system-role mappings."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """System roles shown in the administration UI."""

    LOAN_OFFICER = "loan_officer"
    RISK_ANALYST = "risk_analyst"
    ADMIN = "admin"


class PermissionCode(StrEnum):
    APPLICATION_CREATE = "application:create"
    APPLICATION_READ_OWN = "application:read_own"
    APPLICATION_READ_ALL = "application:read_all"
    PREDICTION_CREATE = "prediction:create"
    PREDICTION_READ_OWN = "prediction:read_own"
    PREDICTION_READ_ALL = "prediction:read_all"
    FEEDBACK_CREATE = "feedback:create"
    FEEDBACK_READ_OWN = "feedback:read_own"
    FEEDBACK_READ_ALL = "feedback:read_all"
    EXPERIMENT_PARTICIPATE = "experiment:participate"
    EXPERIMENT_READ_RESULTS = "experiment:read_results"
    MONITORING_READ = "monitoring:read"
    MONITORING_RUN_CHECK = "monitoring:run_check"
    RETRAINING_CREATE = "retraining:create"
    RETRAINING_READ = "retraining:read"
    RETRAINING_REVIEW = "retraining:review"
    MODEL_READ = "model:read"
    DASHBOARD_READ = "dashboard:read"
    USER_MANAGE = "user:manage"
    ROLE_READ = "role:read"
    AUDIT_READ = "audit:read"


PERMISSION_DESCRIPTIONS: dict[PermissionCode, str] = {
    PermissionCode.APPLICATION_CREATE: "Create loan applications.",
    PermissionCode.APPLICATION_READ_OWN: "Read applications created by the user.",
    PermissionCode.APPLICATION_READ_ALL: "Read every loan application.",
    PermissionCode.PREDICTION_CREATE: "Run and persist model predictions.",
    PermissionCode.PREDICTION_READ_OWN: "Read predictions requested by the user.",
    PermissionCode.PREDICTION_READ_ALL: "Read every prediction.",
    PermissionCode.FEEDBACK_CREATE: "Record or amend a human decision.",
    PermissionCode.FEEDBACK_READ_OWN: "Read decisions recorded by the user.",
    PermissionCode.FEEDBACK_READ_ALL: "Read every recorded decision.",
    PermissionCode.EXPERIMENT_PARTICIPATE: "Participate in the explanation study.",
    PermissionCode.EXPERIMENT_READ_RESULTS: "Read aggregate explanation-study results.",
    PermissionCode.MONITORING_READ: "Read monitoring status and history.",
    PermissionCode.MONITORING_RUN_CHECK: "Run a feature-drift check.",
    PermissionCode.RETRAINING_CREATE: "Open a human retraining-review ticket.",
    PermissionCode.RETRAINING_READ: "Read retraining-review tickets.",
    PermissionCode.RETRAINING_REVIEW: "Approve or reject retraining-review tickets.",
    PermissionCode.MODEL_READ: "Read model and training metadata.",
    PermissionCode.DASHBOARD_READ: "Read the role-aware dashboard.",
    PermissionCode.USER_MANAGE: "Create and administer user accounts.",
    PermissionCode.ROLE_READ: "Read roles and their permission mappings.",
    PermissionCode.AUDIT_READ: "Read security and administration audit events.",
}


ROLE_DESCRIPTIONS: dict[UserRole, str] = {
    UserRole.LOAN_OFFICER: "Creates and reviews their own loan applications.",
    UserRole.RISK_ANALYST: "Reviews portfolio risk, drift, models, and retraining tickets.",
    UserRole.ADMIN: "Administers users and audits and reviews retraining tickets.",
}

_CREATE_PERMISSIONS = {
    PermissionCode.APPLICATION_CREATE,
    PermissionCode.PREDICTION_CREATE,
    PermissionCode.FEEDBACK_CREATE,
}

ROLE_PERMISSIONS: dict[UserRole, frozenset[PermissionCode]] = {
    UserRole.LOAN_OFFICER: frozenset(
        {
            *_CREATE_PERMISSIONS,
            PermissionCode.APPLICATION_READ_OWN,
            PermissionCode.PREDICTION_READ_OWN,
            PermissionCode.FEEDBACK_READ_OWN,
            PermissionCode.EXPERIMENT_PARTICIPATE,
            PermissionCode.DASHBOARD_READ,
        }
    ),
    UserRole.RISK_ANALYST: frozenset(
        {
            *_CREATE_PERMISSIONS,
            PermissionCode.APPLICATION_READ_ALL,
            PermissionCode.PREDICTION_READ_ALL,
            PermissionCode.FEEDBACK_READ_ALL,
            PermissionCode.MONITORING_READ,
            PermissionCode.MONITORING_RUN_CHECK,
            PermissionCode.RETRAINING_CREATE,
            PermissionCode.RETRAINING_READ,
            PermissionCode.MODEL_READ,
            PermissionCode.EXPERIMENT_READ_RESULTS,
            PermissionCode.DASHBOARD_READ,
        }
    ),
    UserRole.ADMIN: frozenset(
        {
            *_CREATE_PERMISSIONS,
            PermissionCode.APPLICATION_READ_ALL,
            PermissionCode.PREDICTION_READ_ALL,
            PermissionCode.FEEDBACK_READ_ALL,
            PermissionCode.MONITORING_READ,
            PermissionCode.MONITORING_RUN_CHECK,
            PermissionCode.RETRAINING_CREATE,
            PermissionCode.RETRAINING_READ,
            PermissionCode.RETRAINING_REVIEW,
            PermissionCode.MODEL_READ,
            PermissionCode.EXPERIMENT_READ_RESULTS,
            PermissionCode.DASHBOARD_READ,
            PermissionCode.USER_MANAGE,
            PermissionCode.ROLE_READ,
            PermissionCode.AUDIT_READ,
        }
    ),
}

ALL_PERMISSION_CODES = frozenset(PERMISSION_DESCRIPTIONS)

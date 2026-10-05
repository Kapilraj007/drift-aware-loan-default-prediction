"""Idempotent RBAC catalogue and local demonstration-user seed."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..core.config import (
    Settings,
    direct_database_url_from_environment,
    mask_database_url,
    optional_environment_value,
)
from ..core.rbac import (
    PERMISSION_DESCRIPTIONS,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    UserRole,
)
from ..core.security import hash_password
from ..models.db_models import (
    Application,
    ExplanationExperimentAssignment,
    ExplanationExperimentExposure,
    Feedback,
    MonitoringSnapshot,
    Permission,
    Prediction,
    RetrainingTicket,
    Role,
    RolePermission,
    User,
)
from ..models.schemas import DriftStatusResponse
from ..services.drift_service import DriftService
from ..services.inference_service import InferenceService
from ..services.shap_service import ShapService
from .session import create_direct_engine

DEMO_USERS: dict[str, tuple[UserRole, str, str, str | None]] = {
    "admin": (UserRole.ADMIN, "Demo Administrator", "admin@demo.local", None),
    "analyst": (UserRole.RISK_ANALYST, "Demo Risk Analyst", "analyst@demo.local", None),
    "officer.explain": (
        UserRole.LOAN_OFFICER,
        "Explanation Demo Officer",
        "officer.explain@demo.local",
        "explanation_shown",
    ),
    "officer.scoreonly": (
        UserRole.LOAN_OFFICER,
        "Score-only Demo Officer",
        "officer.scoreonly@demo.local",
        "score_only",
    ),
}
DEMO_PASSWORD_VARIABLES = {
    "admin": "SEED_ADMIN_PASSWORD",
    "analyst": "SEED_ANALYST_PASSWORD",
    "officer.explain": "SEED_OFFICER_EXPLAIN_PASSWORD",
    "officer.scoreonly": "SEED_OFFICER_SCOREONLY_PASSWORD",
}


def _boolean_environment(name: str, default: bool) -> bool:
    value = optional_environment_value(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def sync_catalogue(session: Session) -> dict[UserRole, Role]:
    """Make system roles, permissions, and mappings exactly match the catalogue."""

    roles_by_name = {role.name: role for role in session.scalars(select(Role)).all()}
    system_roles: dict[UserRole, Role] = {}
    for role_name, description in ROLE_DESCRIPTIONS.items():
        role = roles_by_name.get(role_name.value)
        if role is None:
            role = Role(name=role_name.value, description=description, is_system=True)
            session.add(role)
            session.flush()
        else:
            role.description = description
            role.is_system = True
        system_roles[role_name] = role

    permissions_by_code = {
        permission.code: permission for permission in session.scalars(select(Permission)).all()
    }
    canonical_permissions: dict[str, Permission] = {}
    for code, description in PERMISSION_DESCRIPTIONS.items():
        permission = permissions_by_code.get(code.value)
        if permission is None:
            permission = Permission(code=code.value, description=description)
            session.add(permission)
            session.flush()
        else:
            permission.description = description
        canonical_permissions[code.value] = permission

    system_role_ids = [role.id for role in system_roles.values()]
    if system_role_ids:
        session.execute(
            delete(RolePermission).where(RolePermission.role_id.in_(system_role_ids))
        )
    for role_name, codes in ROLE_PERMISSIONS.items():
        role = system_roles[role_name]
        for code in sorted(codes, key=str):
            session.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=canonical_permissions[code.value].id,
                )
            )

    stale_codes = set(permissions_by_code) - set(canonical_permissions)
    if stale_codes:
        stale_ids = [permissions_by_code[code].id for code in stale_codes]
        session.execute(delete(RolePermission).where(RolePermission.permission_id.in_(stale_ids)))
        session.execute(delete(Permission).where(Permission.id.in_(stale_ids)))
    session.flush()
    return system_roles


def seed_demo_users(session: Session, roles: dict[UserRole, Role]) -> list[User]:
    """Create stable demo identities without rotating hashes on repeated runs."""

    users: list[User] = []
    for username, (role_name, full_name, email, variant) in DEMO_USERS.items():
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            variable = DEMO_PASSWORD_VARIABLES[username]
            password = optional_environment_value(variable) or ""
            if not password:
                raise RuntimeError(f"{variable} is required when demo users are enabled")
            user = User(
                username=username,
                password_hash=hash_password(password),
                role_id=roles[role_name].id,
                email=email,
                full_name=full_name,
                must_change_password=False,
                is_active=True,
            )
            session.add(user)
            session.flush()
        else:
            user.role_id = roles[role_name].id
            user.email = email
            user.full_name = full_name
            user.is_active = True
        users.append(user)

        if variant is not None:
            assignment = session.scalar(
                select(ExplanationExperimentAssignment).where(
                    ExplanationExperimentAssignment.officer_id == user.id
                )
            )
            if assignment is None:
                session.add(
                    ExplanationExperimentAssignment(officer_id=user.id, variant=variant)
                )
            else:
                assignment.variant = variant
    session.flush()
    return users


def _demo_features(index: int) -> dict[str, object]:
    """Return one deterministic, schema-valid synthetic application."""

    grade_number = index % 5
    grade = chr(ord("A") + grade_number)
    issue_year = 2017 + (index % 4)
    issue_month = 1 + (index % 12)
    return {
        "annual_inc": 42_000 + index * 1_350,
        "dti": round(7.5 + (index % 18) * 1.35, 2),
        "revol_util": f"{22 + (index * 7) % 73}%",
        "revol_bal": 4_500 + index * 620,
        "open_acc": 4 + index % 14,
        "total_acc": 12 + index % 31,
        "delinq_2yrs": index % 4 if index % 11 == 0 else 0,
        "inq_last_6mths": index % 4,
        "loan_amnt": 5_000 + (index % 13) * 1_250,
        "term": "60 months" if index % 4 == 0 else "36 months",
        "int_rate": f"{7.2 + grade_number * 3.1 + (index % 3) * 0.4:.1f}%",
        "installment": round(180 + (index % 13) * 47.5, 2),
        "grade": grade,
        "sub_grade": f"{grade}{1 + index % 5}",
        "purpose": (
            "debt_consolidation",
            "credit_card",
            "home_improvement",
            "small_business",
        )[index % 4],
        "emp_length": ("< 1 year", "2 years", "5 years", "10+ years")[index % 4],
        "home_ownership": ("RENT", "MORTGAGE", "OWN")[index % 3],
        "earliest_cr_line": f"Jan-{1992 + index % 16}",
        "issue_d": f"{datetime(issue_year, issue_month, 1):%b-%Y}",
    }


def _monitoring_record(
    session: Session,
    snapshot: object,
    *,
    source: str,
    marker: str,
) -> MonitoringSnapshot:
    payload = DriftStatusResponse.model_validate(
        snapshot.to_dict()  # type: ignore[attr-defined]
    ).model_dump(mode="json")
    payload["demo_marker"] = marker
    record = MonitoringSnapshot(source=source, status=payload["status"], snapshot=payload)
    session.add(record)
    session.flush()
    return record


def seed_demo_data(
    session: Session,
    users: list[User],
    settings: Settings,
    *,
    count: int = 50,
) -> None:
    """Upsert a small showcase dataset scored by the real local model."""

    users_by_name = {user.username: user for user in users}
    officers = [
        users_by_name["officer.explain"],
        users_by_name["officer.scoreonly"],
    ]
    analyst = users_by_name["analyst"]
    admin = users_by_name["admin"]
    inference = InferenceService(settings)
    shap = ShapService()
    drift = DriftService(settings)

    for index in range(count):
        reference = f"DEMO-{index + 1:03d}"
        application = session.scalar(
            select(Application).where(Application.external_reference == reference)
        )
        officer = officers[index % len(officers)]
        if application is None:
            application = Application(
                external_reference=reference,
                raw_features=_demo_features(index),
                created_by_id=officer.id,
            )
            session.add(application)
            session.flush()

        prediction = session.scalar(
            select(Prediction)
            .where(Prediction.application_id == application.id)
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        if prediction is None:
            result = inference.predict(dict(application.raw_features))
            explanation = shap.explain(result)
            detector_state = drift.observe_score(result.score)
            detector_payload = DriftStatusResponse.model_validate(
                detector_state.to_dict()
            ).model_dump(mode="json")
            prediction = Prediction(
                application_id=application.id,
                requested_by_id=officer.id,
                model_version=result.model_version,
                score=result.score,
                threshold=result.threshold,
                risk_flag=result.risk_flag,
                explanation=explanation.to_dict(),
                detector_state=detector_payload,
            )
            session.add(prediction)
            session.flush()
            _monitoring_record(
                session,
                detector_state,
                source="score_observation",
                marker=f"score-{reference}",
            )

        assignment = session.scalar(
            select(ExplanationExperimentAssignment).where(
                ExplanationExperimentAssignment.officer_id == officer.id
            )
        )
        assert assignment is not None
        exposure = session.scalar(
            select(ExplanationExperimentExposure).where(
                ExplanationExperimentExposure.assignment_id == assignment.id,
                ExplanationExperimentExposure.prediction_id == prediction.id,
            )
        )
        if exposure is None:
            session.add(
                ExplanationExperimentExposure(
                    assignment_id=assignment.id,
                    prediction_id=prediction.id,
                    officer_id=officer.id,
                    variant=assignment.variant,
                    explanation_shown=assignment.variant == "explanation_shown",
                )
            )

        history = list(
            session.scalars(
                select(Feedback)
                .where(Feedback.prediction_id == prediction.id)
                .order_by(Feedback.version)
            ).all()
        )
        if not history and index % 5 != 0:
            decision = ("approve", "decline", "escalate")[index % 3]
            agreed = (
                decision in {"decline", "escalate"}
                if prediction.risk_flag
                else decision == "approve"
            )
            first = Feedback(
                prediction_id=prediction.id,
                officer_id=officer.id,
                decision=decision,
                version=1,
                agreed_with_model=agreed,
                note=None if agreed else "Demo override recorded after human review.",
                detector_state=dict(prediction.detector_state),
            )
            session.add(first)
            session.flush()
            if index % 13 == 0:
                session.add(
                    Feedback(
                        prediction_id=prediction.id,
                        officer_id=officer.id,
                        decision="escalate",
                        version=2,
                        amends_feedback_id=first.id,
                        agreed_with_model=True,
                        note="Demo amendment after a second human review.",
                        detector_state=dict(prediction.detector_state),
                    )
                )

    existing_feature_drift = next(
        (
            record
            for record in session.scalars(
                select(MonitoringSnapshot).where(
                    MonitoringSnapshot.source == "feature_drift"
                )
            )
            if record.snapshot.get("demo_marker") == "feature-drift"
        ),
        None,
    )
    if existing_feature_drift is None:
        reference = pd.DataFrame(
            {
                "annual_inc": [45_000 + value * 100 for value in range(100)],
                "dti": [8 + value * 0.05 for value in range(100)],
            }
        )
        current = pd.DataFrame(
            {
                "annual_inc": [95_000 + value * 100 for value in range(100)],
                "dti": [32 + value * 0.05 for value in range(100)],
            }
        )
        feature_snapshot = drift.evaluate_feature_drift(reference, current)
        existing_feature_drift = _monitoring_record(
            session,
            feature_snapshot,
            source="feature_drift",
            marker="feature-drift",
        )

    tickets = {
        ticket.reason: ticket
        for ticket in session.scalars(
            select(RetrainingTicket).where(
                RetrainingTicket.reason.like("[DEMO] %")
            )
        )
    }
    open_reason = "[DEMO] Review the synthetic cohort drift before any retraining."
    if open_reason not in tickets:
        session.add(
            RetrainingTicket(
                monitoring_snapshot_id=existing_feature_drift.id,
                reason=open_reason,
                human_review_confirmed=True,
                status="open",
                requested_by_id=analyst.id,
            )
        )
    reviewed_reason = "[DEMO] Historical drift review for the showcase."
    if reviewed_reason not in tickets:
        session.add(
            RetrainingTicket(
                monitoring_snapshot_id=existing_feature_drift.id,
                reason=reviewed_reason,
                human_review_confirmed=True,
                status="approved",
                requested_by_id=analyst.id,
                reviewed_by_id=admin.id,
                review_note="Approved for demonstration; training remains a separate action.",
                reviewed_at=datetime.now(UTC),
            )
        )
    session.flush()


def reset_demo(session: Session) -> None:
    """Remove only fixed demo identities and rows explicitly tagged as demo data."""

    demo_user_ids = list(
        session.scalars(select(User.id).where(User.username.in_(tuple(DEMO_USERS)))).all()
    )
    demo_application_ids = list(
        session.scalars(
            select(Application.id).where(
                (Application.external_reference.like("DEMO-%"))
                | (Application.created_by_id.in_(demo_user_ids))
            )
        ).all()
    )
    demo_prediction_ids = list(
        session.scalars(
            select(Prediction.id).where(
                (Prediction.requested_by_id.in_(demo_user_ids))
                | (Prediction.application_id.in_(demo_application_ids))
            )
        ).all()
    )
    demo_monitoring_ids = [
        record.id
        for record in session.scalars(select(MonitoringSnapshot)).all()
        if str(record.snapshot.get("demo_marker", "")).startswith(
            ("score-DEMO-", "feature-drift")
        )
    ]
    if demo_prediction_ids or demo_user_ids:
        session.execute(
            delete(ExplanationExperimentExposure).where(
                (ExplanationExperimentExposure.prediction_id.in_(demo_prediction_ids))
                | (ExplanationExperimentExposure.officer_id.in_(demo_user_ids))
            )
        )
        session.execute(
            delete(Feedback).where(
                (Feedback.prediction_id.in_(demo_prediction_ids))
                | (Feedback.officer_id.in_(demo_user_ids))
            )
        )
    if demo_user_ids:
        session.execute(
            delete(ExplanationExperimentAssignment).where(
                ExplanationExperimentAssignment.officer_id.in_(demo_user_ids)
            )
        )
        session.execute(
            delete(RetrainingTicket).where(
                RetrainingTicket.requested_by_id.in_(demo_user_ids)
            )
        )
        session.execute(
            update(RetrainingTicket)
            .where(RetrainingTicket.reviewed_by_id.in_(demo_user_ids))
            .values(reviewed_by_id=None)
        )
    if demo_monitoring_ids:
        session.execute(
            delete(RetrainingTicket).where(
                RetrainingTicket.monitoring_snapshot_id.in_(demo_monitoring_ids)
            )
        )
    if demo_prediction_ids:
        session.execute(delete(Prediction).where(Prediction.id.in_(demo_prediction_ids)))
    if demo_application_ids:
        session.execute(delete(Application).where(Application.id.in_(demo_application_ids)))
    if demo_monitoring_ids:
        session.execute(
            delete(MonitoringSnapshot).where(MonitoringSnapshot.id.in_(demo_monitoring_ids))
        )
    if demo_user_ids:
        session.execute(delete(User).where(User.id.in_(demo_user_ids)))
    session.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-users", action="store_true")
    parser.add_argument("--demo-data", action="store_true")
    parser.add_argument("--reset-demo", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    app_env = (optional_environment_value("APP_ENV") or "development").casefold()
    default_demo_users = _boolean_environment("SEED_DEMO_USERS", app_env != "production")
    demo_users = args.demo_users or default_demo_users
    if app_env == "production" and (demo_users or args.demo_data or args.reset_demo):
        raise RuntimeError("Demo seeding and reset are refused when APP_ENV=production")

    url = direct_database_url_from_environment()
    print(f"Seed target: {mask_database_url(url)}")
    if not args.yes:
        confirmation = input("Continue with this database? [y/N] ").strip().casefold()
        if confirmation not in {"y", "yes"}:
            print("Seed cancelled.")
            return 1

    engine = create_direct_engine(url)
    try:
        with Session(engine) as session, session.begin():
            if args.reset_demo:
                reset_demo(session)
            roles = sync_catalogue(session)
            seeded_users: list[User] = []
            if demo_users:
                seeded_users = seed_demo_users(session, roles)
            if args.demo_data:
                if not seeded_users:
                    raise RuntimeError("--demo-data requires the four demo users")
                seed_demo_data(session, seeded_users, Settings.from_environment())
    finally:
        engine.dispose()
    print("RBAC catalogue synchronized; requested demo users are ready.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Persist and query loan applications for auditable human review."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, case, func, or_, select
from sqlalchemy.orm import Session

from ...core.rbac import PermissionCode
from ...core.security import has_permission, require_any_permission, require_permissions
from ...db.session import get_session
from ...models.db_models import Application, Feedback, Prediction, User
from ...models.schemas import (
    ApplicationCreateRequest,
    ApplicationListItemResponse,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationReviewResponse,
    ApplicationStatus,
    LoanApplicationFeatures,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def application_response(application: Application) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id,
        external_reference=application.external_reference,
        features=LoanApplicationFeatures.model_validate(application.raw_features),
        created_by_id=application.created_by_id,
        created_at=application.created_at,
    )


def assert_application_access(application: Application, current_user: User) -> None:
    """Keep ownership checks separate from table-driven permission checks."""

    if has_permission(current_user, PermissionCode.APPLICATION_READ_ALL):
        return
    if (
        not has_permission(current_user, PermissionCode.APPLICATION_READ_OWN)
        or application.created_by_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access is denied",
        )


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.APPLICATION_CREATE)),
    ],
) -> ApplicationResponse:
    application = Application(
        external_reference=payload.external_reference,
        raw_features=payload.features.as_raw_dict(),
        created_by_id=current_user.id,
    )
    session.add(application)
    session.flush()
    return application_response(application)


def _application_listing_expressions():
    latest_prediction_id = (
        select(Prediction.id)
        .where(Prediction.application_id == Application.id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )
    latest_score = (
        select(Prediction.score)
        .where(Prediction.id == latest_prediction_id)
        .correlate(Application)
        .scalar_subquery()
    )
    latest_risk_flag = (
        select(Prediction.risk_flag)
        .where(Prediction.id == latest_prediction_id)
        .correlate(Application)
        .scalar_subquery()
    )
    current_decision = (
        select(Feedback.decision)
        .where(Feedback.prediction_id == latest_prediction_id)
        .order_by(Feedback.version.desc(), Feedback.created_at.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )
    application_status = case(
        (current_decision == "escalate", ApplicationStatus.ESCALATED.value),
        (current_decision.is_not(None), ApplicationStatus.DECIDED.value),
        (latest_prediction_id.is_not(None), ApplicationStatus.SCORED.value),
        else_=ApplicationStatus.UNSCORED.value,
    )
    return (
        latest_prediction_id,
        latest_score,
        latest_risk_flag,
        current_decision,
        application_status,
    )


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.APPLICATION_READ_OWN,
                PermissionCode.APPLICATION_READ_ALL,
            )
        ),
    ],
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    application_status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    risk_flag: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> ApplicationListResponse:
    """Return a role-aware, server-paginated review queue."""

    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    (
        latest_prediction_id,
        latest_score,
        latest_risk_flag,
        current_decision,
        application_status,
    ) = _application_listing_expressions()
    statement = select(
        Application,
        latest_prediction_id.label("latest_prediction_id"),
        latest_score.label("latest_score"),
        latest_risk_flag.label("latest_risk_flag"),
        current_decision.label("current_decision"),
        application_status.label("application_status"),
    )
    if not has_permission(current_user, PermissionCode.APPLICATION_READ_ALL):
        statement = statement.where(Application.created_by_id == current_user.id)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Application.external_reference.ilike(pattern),
                Application.id.cast(String).ilike(pattern),
            )
        )
    if date_from is not None:
        statement = statement.where(Application.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(Application.created_at <= date_to)
    if application_status_filter is not None:
        statement = statement.where(application_status == application_status_filter.value)
    if risk_flag is not None:
        statement = statement.where(latest_risk_flag == risk_flag)

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = session.execute(
        statement.order_by(Application.created_at.desc(), Application.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        ApplicationListItemResponse(
            **application_response(application).model_dump(),
            status=ApplicationStatus(status_value),
            latest_prediction_id=prediction_id,
            score=score,
            risk_flag=row_risk_flag,
            current_decision=decision,
        )
        for (
            application,
            prediction_id,
            score,
            row_risk_flag,
            decision,
            status_value,
        ) in rows
    ]
    return ApplicationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{application_id}/review", response_model=ApplicationReviewResponse)
def get_application_review(
    application_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.APPLICATION_READ_OWN,
                PermissionCode.APPLICATION_READ_ALL,
            )
        ),
    ],
) -> ApplicationReviewResponse:
    """Fetch the application, latest score, and append-only decision history."""

    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    assert_application_access(application, current_user)
    prediction = session.scalar(
        select(Prediction)
        .where(Prediction.application_id == application.id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(1)
    )
    if prediction is None:
        return ApplicationReviewResponse(
            application=application_response(application),
            latest_prediction=None,
            feedback_history=[],
            current_feedback=None,
        )

    feedback_rows = session.scalars(
        select(Feedback)
        .where(Feedback.prediction_id == prediction.id)
        .order_by(Feedback.version.asc(), Feedback.created_at.asc())
    ).all()
    # Local imports avoid a module cycle: prediction creation needs the
    # application ownership helper above.
    from .routes_feedback import feedback_response
    from .routes_predictions import prediction_response, study_variant_for_user

    history = [
        feedback_response(row, is_current=index == len(feedback_rows) - 1)
        for index, row in enumerate(feedback_rows)
    ]
    return ApplicationReviewResponse(
        application=application_response(application),
        latest_prediction=prediction_response(
            prediction,
            study_variant=study_variant_for_user(session, current_user),
        ),
        feedback_history=history,
        current_feedback=history[-1] if history else None,
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.APPLICATION_READ_OWN,
                PermissionCode.APPLICATION_READ_ALL,
            )
        ),
    ],
) -> ApplicationResponse:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    assert_application_access(application, current_user)
    return application_response(application)

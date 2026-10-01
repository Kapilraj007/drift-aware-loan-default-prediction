"""Persist raw application payloads for reproducible human review and scoring."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import UserRole, get_current_user, require_roles
from ...db.session import get_session
from ...models.db_models import Application, User
from ...models.schemas import ApplicationCreateRequest, ApplicationResponse, LoanApplicationFeatures

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
    """Officers see their records; analysts/admins can inspect the review queue."""

    privileged = {UserRole.RISK_ANALYST.value, UserRole.ADMIN.value}
    if current_user.role not in privileged and application.created_by_id != current_user.id:
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
        Depends(
            require_roles(UserRole.LOAN_OFFICER, UserRole.RISK_ANALYST, UserRole.ADMIN)
        ),
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


@router.get("", response_model=list[ApplicationResponse])
def list_applications(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = 100,
) -> list[ApplicationResponse]:
    safe_limit = min(max(limit, 1), 500)
    statement = select(Application).order_by(Application.created_at.desc()).limit(safe_limit)
    if current_user.role == UserRole.LOAN_OFFICER.value:
        statement = statement.where(Application.created_by_id == current_user.id)
    applications = session.scalars(statement).all()
    return [application_response(application) for application in applications]


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ApplicationResponse:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    assert_application_access(application, current_user)
    return application_response(application)

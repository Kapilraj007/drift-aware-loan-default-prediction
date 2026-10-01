"""Officer-decision audit logging with the detector state at decision time."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import UserRole, require_roles
from ...db.session import get_session
from ...models.db_models import Feedback, Prediction, User
from ...models.schemas import (
    DriftStatusResponse,
    FeedbackCreateRequest,
    FeedbackResponse,
    OfficerDecision,
)
from .deps import get_drift_service

router = APIRouter(prefix="/feedback", tags=["feedback"])


def feedback_response(feedback: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=feedback.id,
        prediction_id=feedback.prediction_id,
        officer_id=feedback.officer_id,
        decision=OfficerDecision(feedback.decision),
        agreed_with_model=feedback.agreed_with_model,
        note=feedback.note,
        detector_state=DriftStatusResponse.model_validate(feedback.detector_state),
        created_at=feedback.created_at,
    )


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_roles(UserRole.LOAN_OFFICER, UserRole.RISK_ANALYST, UserRole.ADMIN)
        ),
    ],
    drift_service: Annotated[object, Depends(get_drift_service)],
) -> FeedbackResponse:
    prediction = session.get(Prediction, payload.prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")
    privileged = {UserRole.RISK_ANALYST.value, UserRole.ADMIN.value}
    if current_user.role not in privileged and prediction.requested_by_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prediction access is denied",
        )
    # This is intentionally a fresh snapshot: it records the monitor state at
    # the officer's action, not merely the state that existed at scoring time.
    detector_state = drift_service.snapshot()
    detector_state_json = DriftStatusResponse.model_validate(detector_state.to_dict()).model_dump(
        mode="json"
    )
    feedback = Feedback(
        prediction_id=prediction.id,
        officer_id=current_user.id,
        decision=payload.decision.value,
        agreed_with_model=payload.agreed_with_model,
        note=payload.note,
        detector_state=detector_state_json,
    )
    session.add(feedback)
    session.flush()
    return feedback_response(feedback)


@router.get("", response_model=list[FeedbackResponse])
def list_feedback(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    limit: int = 100,
) -> list[FeedbackResponse]:
    del current_user
    safe_limit = min(max(limit, 1), 500)
    feedback_rows = session.scalars(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(safe_limit)
    ).all()
    return [feedback_response(row) for row in feedback_rows]

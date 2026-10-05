"""Append-only human-decision history with ownership and amendment rules."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from ...core.rbac import PermissionCode
from ...core.security import has_permission, require_any_permission, require_permissions
from ...db.session import get_session
from ...models.db_models import Feedback, Prediction, User
from ...models.schemas import (
    DriftStatusResponse,
    FeedbackCreateRequest,
    FeedbackListResponse,
    FeedbackResponse,
    OfficerDecision,
)
from .deps import get_drift_service

router = APIRouter(prefix="/feedback", tags=["feedback"])


def feedback_response(feedback: Feedback, *, is_current: bool = True) -> FeedbackResponse:
    return FeedbackResponse(
        id=feedback.id,
        prediction_id=feedback.prediction_id,
        officer_id=feedback.officer_id,
        version=feedback.version,
        amends_feedback_id=feedback.amends_feedback_id,
        is_current=is_current,
        decision=OfficerDecision(feedback.decision),
        agreed_with_model=feedback.agreed_with_model,
        note=feedback.note,
        detector_state=DriftStatusResponse.model_validate(feedback.detector_state),
        created_at=feedback.created_at,
    )


def _assert_feedback_target_access(prediction: Prediction, current_user: User) -> None:
    if has_permission(current_user, PermissionCode.PREDICTION_READ_ALL):
        return
    if prediction.requested_by_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prediction access is denied",
        )


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.FEEDBACK_CREATE)),
    ],
    drift_service: Annotated[object, Depends(get_drift_service)],
) -> FeedbackResponse:
    # Locking the prediction serializes version allocation for concurrent amendments.
    prediction = session.get(Prediction, payload.prediction_id, with_for_update=True)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")
    _assert_feedback_target_access(prediction, current_user)
    previous = session.scalar(
        select(Feedback)
        .where(Feedback.prediction_id == prediction.id)
        .order_by(Feedback.version.desc(), Feedback.created_at.desc())
        .limit(1)
    )
    note = payload.note.strip() if payload.note else None
    if previous is not None and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "field": "note",
                    "message": "A note is required when amending a prior decision",
                }
            ],
        )
    if payload.agreed_with_model is False and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "field": "note",
                    "message": "A note is required when overriding the model",
                }
            ],
        )

    detector_state = drift_service.snapshot()
    detector_state_json = DriftStatusResponse.model_validate(detector_state.to_dict()).model_dump(
        mode="json"
    )
    feedback = Feedback(
        prediction_id=prediction.id,
        officer_id=current_user.id,
        decision=payload.decision.value,
        version=previous.version + 1 if previous is not None else 1,
        amends_feedback_id=previous.id if previous is not None else None,
        agreed_with_model=payload.agreed_with_model,
        note=note,
        detector_state=detector_state_json,
    )
    session.add(feedback)
    session.flush()
    return feedback_response(feedback)


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.FEEDBACK_READ_OWN,
                PermissionCode.FEEDBACK_READ_ALL,
            )
        ),
    ],
    limit: int = 50,
    offset: int = 0,
    prediction_id: str | None = None,
    decision: OfficerDecision | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> FeedbackListResponse:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    later = aliased(Feedback)
    is_current = (
        ~select(later.id)
        .where(
            later.prediction_id == Feedback.prediction_id,
            later.version > Feedback.version,
        )
        .exists()
    )
    statement = select(Feedback, is_current.label("is_current"))
    if not has_permission(current_user, PermissionCode.FEEDBACK_READ_ALL):
        statement = statement.where(Feedback.officer_id == current_user.id)
    if prediction_id:
        statement = statement.where(Feedback.prediction_id == prediction_id)
    if decision is not None:
        statement = statement.where(Feedback.decision == decision.value)
    if date_from is not None:
        statement = statement.where(Feedback.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(Feedback.created_at <= date_to)
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = session.execute(
        statement.order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return FeedbackListResponse(
        items=[feedback_response(row, is_current=current) for row, current in rows],
        total=total,
        limit=limit,
        offset=offset,
    )

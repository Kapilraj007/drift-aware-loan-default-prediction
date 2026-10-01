"""Persist officer-level explanation-study assignments and treatment exposures."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import UserRole, require_roles
from ...db.session import get_session
from ...models.db_models import (
    ExplanationExperimentAssignment,
    ExplanationExperimentExposure,
    Prediction,
    User,
)
from ...models.schemas import (
    ExplanationAssignmentResponse,
    ExplanationExposureCreateRequest,
    ExplanationExposureResponse,
    ExplanationVariant,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _variant_for_officer(officer_id: str) -> ExplanationVariant:
    """Use a stable, approximately even split without trusting client input."""

    digest = hashlib.sha256(officer_id.encode("utf-8")).digest()
    if digest[0] % 2 == 0:
        return ExplanationVariant.EXPLANATION_SHOWN
    return ExplanationVariant.SCORE_ONLY


def get_or_create_assignment(
    session: Session, officer_id: str
) -> ExplanationExperimentAssignment:
    """Return the immutable assignment for one officer, creating it on first use."""

    assignment = session.scalar(
        select(ExplanationExperimentAssignment).where(
            ExplanationExperimentAssignment.officer_id == officer_id
        )
    )
    if assignment is None:
        assignment = ExplanationExperimentAssignment(
            officer_id=officer_id,
            variant=_variant_for_officer(officer_id).value,
        )
        session.add(assignment)
        session.flush()
    return assignment


def assignment_response(
    assignment: ExplanationExperimentAssignment,
) -> ExplanationAssignmentResponse:
    return ExplanationAssignmentResponse(
        id=assignment.id,
        variant=ExplanationVariant(assignment.variant),
        created_at=assignment.created_at,
    )


def exposure_response(exposure: ExplanationExperimentExposure) -> ExplanationExposureResponse:
    return ExplanationExposureResponse(
        id=exposure.id,
        prediction_id=exposure.prediction_id,
        assignment_id=exposure.assignment_id,
        variant=ExplanationVariant(exposure.variant),
        explanation_shown=exposure.explanation_shown,
        created_at=exposure.created_at,
    )


@router.get("/explanation-assignment", response_model=ExplanationAssignmentResponse)
def explanation_assignment(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_roles(UserRole.LOAN_OFFICER))],
) -> ExplanationAssignmentResponse:
    """Return a durable A/B variant for the authenticated study officer."""

    return assignment_response(get_or_create_assignment(session, current_user.id))


@router.post(
    "/explanation-exposures",
    response_model=ExplanationExposureResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_explanation_exposure(
    payload: ExplanationExposureCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_roles(UserRole.LOAN_OFFICER))],
) -> ExplanationExposureResponse:
    """Audit a score-review exposure without allowing an officer to choose its arm."""

    prediction = session.get(Prediction, payload.prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")
    if prediction.requested_by_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prediction access is denied",
        )

    assignment = get_or_create_assignment(session, current_user.id)
    exposure = session.scalar(
        select(ExplanationExperimentExposure).where(
            ExplanationExperimentExposure.assignment_id == assignment.id,
            ExplanationExperimentExposure.prediction_id == prediction.id,
        )
    )
    if exposure is None:
        variant = ExplanationVariant(assignment.variant)
        exposure = ExplanationExperimentExposure(
            assignment_id=assignment.id,
            prediction_id=prediction.id,
            officer_id=current_user.id,
            variant=variant.value,
            explanation_shown=variant == ExplanationVariant.EXPLANATION_SHOWN,
        )
        session.add(exposure)
        session.flush()
    return exposure_response(exposure)

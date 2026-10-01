"""Score persisted or one-off applications with an auditable model response."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.security import UserRole, get_current_user, require_roles
from ...db.session import get_session
from ...models.db_models import Application, Prediction, User
from ...models.schemas import (
    DirectPredictionRequest,
    DriftStatusResponse,
    ExplanationResponse,
    ExplanationVariant,
    MonitoringSnapshotSource,
    PredictionResponse,
)
from ...services.inference_service import InferenceService, ModelArtifactError
from ...services.shap_service import ShapService
from .deps import get_drift_service, get_inference_service, get_shap_service
from .routes_applications import assert_application_access
from .routes_experiments import get_or_create_assignment
from .routes_monitoring import persist_monitoring_snapshot

router = APIRouter(prefix="/predictions", tags=["predictions"])


def _study_variant_for_user(
    session: Session, current_user: User
) -> ExplanationVariant | None:
    if current_user.role != UserRole.LOAN_OFFICER.value:
        return None
    # Create the durable assignment as part of the first score, rather than
    # relying on the frontend's separate assignment request to win a race.
    # That ensures a score-only officer never receives SHAP contributors in
    # their initial prediction response.
    assignment = get_or_create_assignment(session, current_user.id)
    return ExplanationVariant(assignment.variant)


def prediction_response(
    prediction: Prediction, *, study_variant: ExplanationVariant | None = None
) -> PredictionResponse:
    explanation = ExplanationResponse.model_validate(prediction.explanation)
    if study_variant == ExplanationVariant.SCORE_ONLY:
        explanation = ExplanationResponse(
            available=False,
            narrative="Explanation withheld for the score-only study condition.",
        )
    return PredictionResponse(
        id=prediction.id,
        application_id=prediction.application_id,
        model_version=prediction.model_version,
        score=prediction.score,
        threshold=prediction.threshold,
        risk_flag=prediction.risk_flag,
        explanation=explanation,
        study_variant=study_variant,
        detector_state=DriftStatusResponse.model_validate(prediction.detector_state),
        created_at=prediction.created_at,
    )


@router.post("", response_model=PredictionResponse, status_code=status.HTTP_201_CREATED)
def create_prediction(
    payload: DirectPredictionRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_roles(UserRole.LOAN_OFFICER, UserRole.RISK_ANALYST, UserRole.ADMIN)
        ),
    ],
    inference_service: Annotated[InferenceService, Depends(get_inference_service)],
    shap_service: Annotated[ShapService, Depends(get_shap_service)],
    drift_service: Annotated[object, Depends(get_drift_service)],
) -> PredictionResponse:
    application: Application | None = None
    if payload.application_id is not None:
        application = session.get(Application, payload.application_id)
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )
        assert_application_access(application, current_user)
        raw_features = dict(application.raw_features)
    else:
        assert payload.features is not None  # enforced by the request validator
        raw_features = payload.features.as_raw_dict()

    try:
        result = inference_service.predict(raw_features)
    except ModelArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model is not ready for scoring: {exc}",
        ) from exc
    explanation = shap_service.explain(result)
    detector_state = drift_service.observe_score(result.score)
    detector_state_json = DriftStatusResponse.model_validate(detector_state.to_dict()).model_dump(
        mode="json"
    )
    prediction = Prediction(
        application_id=application.id if application is not None else None,
        requested_by_id=current_user.id,
        model_version=result.model_version,
        score=result.score,
        threshold=result.threshold,
        risk_flag=result.risk_flag,
        explanation=explanation.to_dict(),
        detector_state=detector_state_json,
    )
    session.add(prediction)
    session.flush()
    persist_monitoring_snapshot(
        session,
        detector_state,
        source=MonitoringSnapshotSource.SCORE_OBSERVATION,
    )
    return prediction_response(
        prediction,
        study_variant=_study_variant_for_user(session, current_user),
    )


@router.get("/{prediction_id}", response_model=PredictionResponse)
def get_prediction(
    prediction_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PredictionResponse:
    prediction = session.get(Prediction, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")
    privileged = {UserRole.RISK_ANALYST.value, UserRole.ADMIN.value}
    if current_user.role not in privileged and prediction.requested_by_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prediction access is denied",
        )
    return prediction_response(
        prediction,
        study_variant=_study_variant_for_user(session, current_user),
    )

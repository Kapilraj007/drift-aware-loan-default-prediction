"""Score and query applications with permission-aware explanation masking."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.rbac import PermissionCode
from ...core.security import has_permission, require_any_permission, require_permissions
from ...db.session import get_session
from ...models.db_models import Application, Feedback, Prediction, User
from ...models.schemas import (
    DirectPredictionRequest,
    DriftStatusResponse,
    ExplanationResponse,
    ExplanationVariant,
    MonitoringSnapshotSource,
    PredictionListResponse,
    PredictionResponse,
)
from ...services.inference_service import (
    InferenceService,
    InputValidationError,
    ModelArtifactError,
)
from ...services.shap_service import ShapService
from .deps import get_drift_service, get_inference_service, get_shap_service
from .routes_applications import assert_application_access
from .routes_experiments import get_or_create_assignment
from .routes_monitoring import persist_monitoring_snapshot

router = APIRouter(prefix="/predictions", tags=["predictions"])


def study_variant_for_user(session: Session, current_user: User) -> ExplanationVariant | None:
    """Return the server-controlled study arm only for eligible participants."""

    if not has_permission(current_user, PermissionCode.EXPERIMENT_PARTICIPATE):
        return None
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
        requested_by_id=prediction.requested_by_id,
        model_version=prediction.model_version,
        score=prediction.score,
        threshold=prediction.threshold,
        risk_flag=prediction.risk_flag,
        explanation=explanation,
        study_variant=study_variant,
        detector_state=DriftStatusResponse.model_validate(prediction.detector_state),
        created_at=prediction.created_at,
    )


def assert_prediction_access(prediction: Prediction, current_user: User) -> None:
    if has_permission(current_user, PermissionCode.PREDICTION_READ_ALL):
        return
    if (
        not has_permission(current_user, PermissionCode.PREDICTION_READ_OWN)
        or prediction.requested_by_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Prediction access is denied",
        )


@router.post("", response_model=PredictionResponse, status_code=status.HTTP_201_CREATED)
def create_prediction(
    payload: DirectPredictionRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.PREDICTION_CREATE)),
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
        assert payload.features is not None
        raw_features = payload.features.as_raw_dict()

    try:
        result = inference_service.predict(raw_features)
    except InputValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
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
        study_variant=study_variant_for_user(session, current_user),
    )


@router.get("", response_model=PredictionListResponse)
def list_predictions(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.PREDICTION_READ_OWN,
                PermissionCode.PREDICTION_READ_ALL,
            )
        ),
    ],
    limit: int = 50,
    offset: int = 0,
    risk_flag: bool | None = None,
    decision_status: str | None = None,
    application_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> PredictionListResponse:
    """Return predictions without ever leaking an officer's withheld explanation."""

    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    statement = select(Prediction)
    if not has_permission(current_user, PermissionCode.PREDICTION_READ_ALL):
        statement = statement.where(Prediction.requested_by_id == current_user.id)
    if risk_flag is not None:
        statement = statement.where(Prediction.risk_flag == risk_flag)
    if application_id is not None:
        statement = statement.where(Prediction.application_id == application_id)
    if date_from is not None:
        statement = statement.where(Prediction.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(Prediction.created_at <= date_to)
    if decision_status:
        latest_decision = (
            select(Feedback.decision)
            .where(Feedback.prediction_id == Prediction.id)
            .order_by(Feedback.version.desc(), Feedback.created_at.desc())
            .limit(1)
            .correlate(Prediction)
            .scalar_subquery()
        )
        normalized = decision_status.strip().lower()
        if normalized == "pending":
            statement = statement.where(latest_decision.is_(None))
        elif normalized == "decided":
            statement = statement.where(latest_decision.is_not(None))
        elif normalized in {"approve", "decline", "escalate"}:
            statement = statement.where(latest_decision == normalized)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="decision_status must be pending, decided, approve, decline, or escalate",
            )

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    predictions = session.scalars(
        statement.order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    variant = study_variant_for_user(session, current_user)
    return PredictionListResponse(
        items=[
            prediction_response(prediction, study_variant=variant) for prediction in predictions
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{prediction_id}", response_model=PredictionResponse)
def get_prediction(
    prediction_id: str,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(
            require_any_permission(
                PermissionCode.PREDICTION_READ_OWN,
                PermissionCode.PREDICTION_READ_ALL,
            )
        ),
    ],
) -> PredictionResponse:
    prediction = session.get(Prediction, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")
    assert_prediction_access(prediction, current_user)
    return prediction_response(
        prediction,
        study_variant=study_variant_for_user(session, current_user),
    )

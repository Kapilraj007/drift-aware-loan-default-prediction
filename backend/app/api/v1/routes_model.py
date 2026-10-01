"""Read-only access to the validated training artifact contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import User, UserRole, require_roles
from ...models.schemas import ModelMetadataResponse, TrainingRunsResponse
from ...services.inference_service import InferenceService, ModelArtifactError
from .deps import get_inference_service

router = APIRouter(tags=["model"])


@router.get("/model", response_model=ModelMetadataResponse)
def get_model_metadata(
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    inference_service: Annotated[InferenceService, Depends(get_inference_service)],
) -> ModelMetadataResponse:
    del current_user
    try:
        return ModelMetadataResponse.model_validate(inference_service.describe())
    except ModelArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model artifact is not ready: {exc}",
        ) from exc


@router.get("/training-runs", response_model=TrainingRunsResponse)
def get_training_runs(
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    inference_service: Annotated[InferenceService, Depends(get_inference_service)],
) -> TrainingRunsResponse:
    """Expose recorded run metadata; model training itself remains a CLI job."""

    del current_user
    try:
        metadata = inference_service.describe().get("metadata", {})
    except ModelArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model artifact is not ready: {exc}",
        ) from exc
    if not isinstance(metadata, dict):  # defensive contract boundary
        return TrainingRunsResponse()
    runs = metadata.get("training_runs", metadata.get("training_run", []))
    if isinstance(runs, dict):
        runs = [runs]
    if not isinstance(runs, list):
        runs = []
    return TrainingRunsResponse(runs=[item for item in runs if isinstance(item, dict)])

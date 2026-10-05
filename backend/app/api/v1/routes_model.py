"""Read-only access to the validated training artifact contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.rbac import PermissionCode
from ...core.security import require_permissions
from ...models.db_models import User
from ...models.schemas import ModelMetadataResponse, TrainingRunsResponse
from ...services.inference_service import InferenceService, ModelArtifactError
from .deps import get_inference_service

router = APIRouter(tags=["model"])


@router.get("/model", response_model=ModelMetadataResponse)
def get_model_metadata(
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.MODEL_READ)),
    ],
    inference_service: Annotated[InferenceService, Depends(get_inference_service)],
) -> ModelMetadataResponse:
    del current_user
    try:
        description = inference_service.describe()
    except ModelArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model artifact is not ready: {exc}",
        ) from exc
    metadata = description.get("metadata", {})
    synthetic_demo = bool(
        description.get("synthetic_demo")
        or (isinstance(metadata, dict) and metadata.get("synthetic_demo"))
    )
    return ModelMetadataResponse.model_validate({**description, "synthetic_demo": synthetic_demo})


@router.get("/training-runs", response_model=TrainingRunsResponse)
def get_training_runs(
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.MODEL_READ)),
    ],
    inference_service: Annotated[InferenceService, Depends(get_inference_service)],
) -> TrainingRunsResponse:
    """Expose recorded run metadata; model training itself remains a CLI job."""

    del current_user
    try:
        description = inference_service.describe()
    except ModelArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model artifact is not ready: {exc}",
        ) from exc
    metadata = description.get("metadata", {})
    synthetic_demo = bool(
        description.get("synthetic_demo")
        or (isinstance(metadata, dict) and metadata.get("synthetic_demo"))
    )
    if not isinstance(metadata, dict):
        return TrainingRunsResponse(synthetic_demo=synthetic_demo)
    runs = metadata.get("training_runs", metadata.get("training_run", []))
    if isinstance(runs, dict):
        runs = [runs]
    if not isinstance(runs, list):
        runs = []
    return TrainingRunsResponse(
        runs=[item for item in runs if isinstance(item, dict)],
        synthetic_demo=synthetic_demo,
    )

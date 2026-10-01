"""FastAPI dependencies that retrieve per-app service instances."""

from __future__ import annotations

from fastapi import Request

from ...services.drift_service import DriftService
from ...services.inference_service import InferenceService
from ...services.shap_service import ShapService


def get_inference_service(request: Request) -> InferenceService:
    return request.app.state.inference_service


def get_shap_service(request: Request) -> ShapService:
    return request.app.state.shap_service


def get_drift_service(request: Request) -> DriftService:
    return request.app.state.drift_service

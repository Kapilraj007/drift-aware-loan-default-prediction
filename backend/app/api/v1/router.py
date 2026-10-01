"""Aggregate version-one API router."""

from fastapi import APIRouter

from . import (
    routes_applications,
    routes_auth,
    routes_experiments,
    routes_feedback,
    routes_model,
    routes_monitoring,
    routes_predictions,
    routes_retraining,
)

api_router = APIRouter()
api_router.include_router(routes_auth.router)
api_router.include_router(routes_applications.router)
api_router.include_router(routes_predictions.router)
api_router.include_router(routes_feedback.router)
api_router.include_router(routes_experiments.router)
api_router.include_router(routes_monitoring.router)
api_router.include_router(routes_retraining.router)
api_router.include_router(routes_model.router)

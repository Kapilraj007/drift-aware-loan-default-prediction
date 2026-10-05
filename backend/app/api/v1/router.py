"""Aggregate version-one API router."""

from fastapi import APIRouter

from . import (
    routes_admin,
    routes_applications,
    routes_auth,
    routes_dashboard,
    routes_experiments,
    routes_feedback,
    routes_model,
    routes_monitoring,
    routes_predictions,
    routes_reference,
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
api_router.include_router(routes_dashboard.router)
api_router.include_router(routes_reference.router)
api_router.include_router(routes_admin.users_router)
api_router.include_router(routes_admin.roles_router)
api_router.include_router(routes_admin.audit_router)

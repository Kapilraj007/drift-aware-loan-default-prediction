"""Analyst endpoints for score-stream state and per-feature KS checks."""

from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import User, UserRole, require_roles
from ...db.session import get_session
from ...models.db_models import MonitoringSnapshot
from ...models.schemas import (
    DriftStatusResponse,
    FeatureDriftRequest,
    FeatureDriftResponse,
    MonitoringHistoryResponse,
    MonitoringHistorySnapshotResponse,
    MonitoringSnapshotSource,
)
from .deps import get_drift_service

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _status_response(snapshot: Any) -> DriftStatusResponse:
    return DriftStatusResponse.model_validate(snapshot.to_dict())


def persist_monitoring_snapshot(
    session: Session,
    snapshot: Any,
    *,
    source: MonitoringSnapshotSource,
) -> MonitoringSnapshot:
    """Store only aggregate detector state, never the input rows used for a KS test."""

    state = _status_response(snapshot)
    record = MonitoringSnapshot(
        source=source.value,
        status=state.status,
        snapshot=state.model_dump(mode="json"),
    )
    session.add(record)
    session.flush()
    return record


def _history_response(record: MonitoringSnapshot) -> MonitoringHistorySnapshotResponse:
    return MonitoringHistorySnapshotResponse(
        id=record.id,
        source=MonitoringSnapshotSource(record.source),
        snapshot=DriftStatusResponse.model_validate(record.snapshot),
        created_at=record.created_at,
    )


@router.get("/history", response_model=MonitoringHistoryResponse)
def monitoring_history(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    limit: int = 100,
) -> MonitoringHistoryResponse:
    """Return the most recent persisted monitoring events in chronological order."""

    del current_user
    safe_limit = min(max(limit, 1), 500)
    records = session.scalars(
        select(MonitoringSnapshot)
        .order_by(MonitoringSnapshot.created_at.desc())
        .limit(safe_limit)
    ).all()
    snapshots = [_history_response(item) for item in reversed(records)]
    return MonitoringHistoryResponse(snapshots=snapshots)


@router.get("/status", response_model=DriftStatusResponse)
def monitoring_status(
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    drift_service: Annotated[object, Depends(get_drift_service)],
) -> DriftStatusResponse:
    del current_user
    return _status_response(drift_service.snapshot())


@router.post("/feature-drift", response_model=FeatureDriftResponse)
def feature_drift(
    payload: FeatureDriftRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    drift_service: Annotated[object, Depends(get_drift_service)],
) -> FeatureDriftResponse:
    del current_user
    try:
        snapshot = drift_service.evaluate_feature_drift(
            pd.DataFrame(payload.reference_rows),
            pd.DataFrame(payload.current_rows),
            alpha=payload.alpha,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not evaluate feature drift: {exc}",
        ) from exc
    response = snapshot.to_dict()
    response["evaluated_features"] = len(snapshot.feature_results)
    persist_monitoring_snapshot(
        session,
        snapshot,
        source=MonitoringSnapshotSource.FEATURE_DRIFT,
    )
    return FeatureDriftResponse.model_validate(response)

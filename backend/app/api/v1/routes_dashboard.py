"""Role-aware dashboard aggregates computed in bounded SQL queries."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ...core.rbac import PermissionCode
from ...core.security import has_permission, require_permissions
from ...db.session import get_session
from ...models.db_models import (
    Application,
    Feedback,
    MonitoringSnapshot,
    Prediction,
    RetrainingTicket,
    User,
)
from ...models.schemas import (
    ApplicationListItemResponse,
    ApplicationStatus,
    DashboardSummaryResponse,
    ScoreDistributionBin,
)
from .routes_applications import (
    _application_listing_expressions,
    application_response,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _latest_predictions_subquery():
    ranked = (
        select(
            Prediction.id.label("id"),
            Prediction.application_id.label("application_id"),
            Prediction.score.label("score"),
            Prediction.risk_flag.label("risk_flag"),
            func.row_number()
            .over(
                partition_by=Prediction.application_id,
                order_by=(Prediction.created_at.desc(), Prediction.id.desc()),
            )
            .label("position"),
        )
        .where(Prediction.application_id.is_not(None))
        .subquery()
    )
    return (
        select(
            ranked.c.id,
            ranked.c.application_id,
            ranked.c.score,
            ranked.c.risk_flag,
        )
        .where(ranked.c.position == 1)
        .subquery()
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_permissions(PermissionCode.DASHBOARD_READ)),
    ],
) -> DashboardSummaryResponse:
    """Return portfolio or own-record aggregates based on read-all permission."""

    read_all = has_permission(current_user, PermissionCode.APPLICATION_READ_ALL)
    owner_filter = None if read_all else Application.created_by_id == current_user.id

    application_count_statement = select(func.count(Application.id))
    if owner_filter is not None:
        application_count_statement = application_count_statement.where(owner_filter)
    applications = int(session.scalar(application_count_statement) or 0)

    latest = _latest_predictions_subquery()
    latest_statement = select(
        latest.c.id,
        latest.c.application_id,
        latest.c.score,
        latest.c.risk_flag,
    ).join(Application, Application.id == latest.c.application_id)
    if owner_filter is not None:
        latest_statement = latest_statement.where(owner_filter)
    latest_rows = latest_statement.subquery()
    scored, risk_flag_rate = session.execute(
        select(
            func.count(latest_rows.c.id),
            func.avg(case((latest_rows.c.risk_flag.is_(True), 1.0), else_=0.0)),
        )
    ).one()
    scored = int(scored or 0)
    risk_flag_rate = float(risk_flag_rate) if risk_flag_rate is not None else None

    latest_feedback_versions = (
        select(
            Feedback.prediction_id.label("prediction_id"),
            func.max(Feedback.version).label("version"),
        )
        .group_by(Feedback.prediction_id)
        .subquery()
    )
    decision_rows = session.execute(
        select(Feedback.decision, Feedback.agreed_with_model)
        .join(
            latest_feedback_versions,
            (latest_feedback_versions.c.prediction_id == Feedback.prediction_id)
            & (latest_feedback_versions.c.version == Feedback.version),
        )
        .join(latest_rows, latest_rows.c.id == Feedback.prediction_id)
    ).all()
    decision_mix = {"approve": 0, "decline": 0, "escalate": 0}
    for decision, _agreement in decision_rows:
        decision_mix[decision] = decision_mix.get(decision, 0) + 1
    decided = len(decision_rows)
    rated = [agreement for _decision, agreement in decision_rows if agreement is not None]
    agreements = sum(bool(agreement) for agreement in rated)
    agreement_rate = agreements / len(rated) if rated else None
    override_rate = (len(rated) - agreements) / len(rated) if rated else None

    bin_index = case(
        (latest_rows.c.score >= 1.0, 9),
        else_=func.floor(latest_rows.c.score * 10),
    ).label("bin_index")
    bin_rows = session.execute(
        select(bin_index, func.count()).group_by(bin_index).order_by(bin_index)
    ).all()
    score_distribution = [
        ScoreDistributionBin(
            minimum=float(index) / 10,
            maximum=(float(index) + 1) / 10,
            count=int(count),
        )
        for index, count in bin_rows
    ]

    latest_drift_status = (
        session.scalar(
            select(MonitoringSnapshot.status)
            .order_by(MonitoringSnapshot.created_at.desc(), MonitoringSnapshot.id.desc())
            .limit(1)
        )
        or "not_observed"
    )
    open_tickets = int(
        session.scalar(
            select(func.count(RetrainingTicket.id)).where(RetrainingTicket.status == "open")
        )
        or 0
    )

    (
        latest_prediction_id,
        latest_score,
        latest_risk_flag,
        current_decision,
        application_status,
    ) = _application_listing_expressions()
    recent_statement = select(
        Application,
        latest_prediction_id,
        latest_score,
        latest_risk_flag,
        current_decision,
        application_status,
    )
    if owner_filter is not None:
        recent_statement = recent_statement.where(owner_filter)
    recent_rows = session.execute(
        recent_statement.order_by(Application.created_at.desc(), Application.id.desc()).limit(5)
    ).all()
    recent_applications = [
        ApplicationListItemResponse(
            **application_response(application).model_dump(),
            status=ApplicationStatus(status_value),
            latest_prediction_id=prediction_id,
            score=score,
            risk_flag=row_risk_flag,
            current_decision=decision,
        )
        for application, prediction_id, score, row_risk_flag, decision, status_value in recent_rows
    ]
    return DashboardSummaryResponse(
        applications=applications,
        scored=scored,
        decided=decided,
        pending=max(scored - decided, 0),
        risk_flag_rate=risk_flag_rate,
        decision_mix=decision_mix,
        agreement_rate=agreement_rate,
        override_rate=override_rate,
        latest_drift_status=latest_drift_status,
        open_tickets=open_tickets,
        score_distribution=score_distribution,
        recent_applications=recent_applications,
    )

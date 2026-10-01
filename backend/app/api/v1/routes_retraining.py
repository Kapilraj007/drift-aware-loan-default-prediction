"""Human-gated retraining review tickets with no automatic training action."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import UserRole, require_roles
from ...db.session import get_session
from ...models.db_models import MonitoringSnapshot, RetrainingTicket, User
from ...models.schemas import (
    RetrainingTicketCreateRequest,
    RetrainingTicketResponse,
    RetrainingTicketReviewDecision,
    RetrainingTicketReviewRequest,
    RetrainingTicketStatus,
)

router = APIRouter(prefix="/retraining-tickets", tags=["retraining"])


def ticket_response(ticket: RetrainingTicket) -> RetrainingTicketResponse:
    return RetrainingTicketResponse(
        id=ticket.id,
        monitoring_snapshot_id=ticket.monitoring_snapshot_id,
        reason=ticket.reason,
        human_review_confirmed=ticket.human_review_confirmed,
        status=RetrainingTicketStatus(ticket.status),
        requested_by_id=ticket.requested_by_id,
        reviewed_by_id=ticket.reviewed_by_id,
        review_note=ticket.review_note,
        created_at=ticket.created_at,
        reviewed_at=ticket.reviewed_at,
    )


def _latest_drift_snapshot(session: Session) -> MonitoringSnapshot | None:
    return session.scalar(
        select(MonitoringSnapshot)
        .where(MonitoringSnapshot.status == "drift_detected")
        .order_by(MonitoringSnapshot.created_at.desc())
        .limit(1)
    )


@router.post("", response_model=RetrainingTicketResponse, status_code=status.HTTP_201_CREATED)
def create_retraining_ticket(
    payload: RetrainingTicketCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
) -> RetrainingTicketResponse:
    """Log a human-confirmed review request without enqueueing any work."""

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reason is required",
        )
    snapshot = _latest_drift_snapshot(session)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A persisted drift-detected monitoring snapshot is required",
        )
    ticket = RetrainingTicket(
        monitoring_snapshot_id=snapshot.id,
        reason=reason,
        human_review_confirmed=payload.human_review_confirmed,
        requested_by_id=current_user.id,
        status=RetrainingTicketStatus.OPEN.value,
    )
    session.add(ticket)
    session.flush()
    return ticket_response(ticket)


@router.get("", response_model=list[RetrainingTicketResponse])
def list_retraining_tickets(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.RISK_ANALYST, UserRole.ADMIN)),
    ],
    limit: int = 100,
) -> list[RetrainingTicketResponse]:
    """List review requests, newest first, for authorized monitoring staff."""

    del current_user
    safe_limit = min(max(limit, 1), 500)
    tickets = session.scalars(
        select(RetrainingTicket).order_by(RetrainingTicket.created_at.desc()).limit(safe_limit)
    ).all()
    return [ticket_response(ticket) for ticket in tickets]


@router.post("/{ticket_id}/review", response_model=RetrainingTicketResponse)
def review_retraining_ticket(
    ticket_id: str,
    payload: RetrainingTicketReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> RetrainingTicketResponse:
    """Record an administrative disposition only; no model work is invoked."""

    ticket = session.get(RetrainingTicket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retraining ticket not found",
        )
    if ticket.status != RetrainingTicketStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Retraining ticket has already been reviewed",
        )
    if payload.decision == RetrainingTicketReviewDecision.APPROVE:
        ticket.status = RetrainingTicketStatus.APPROVED.value
    else:
        ticket.status = RetrainingTicketStatus.REJECTED.value
    ticket.reviewed_by_id = current_user.id
    ticket.review_note = payload.note
    ticket.reviewed_at = datetime.now(UTC)
    session.flush()
    return ticket_response(ticket)

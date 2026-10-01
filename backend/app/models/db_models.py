"""SQLite-compatible SQLAlchemy persistence models.

The tables intentionally capture audit context rather than making a lending
decision.  A prediction is a decision-support record; officer feedback remains
the human action of record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _new_id() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all backend tables."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    applications: Mapped[list[Application]] = relationship(back_populates="created_by")
    feedback_entries: Mapped[list[Feedback]] = relationship(back_populates="officer")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    external_reference: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    raw_features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    created_by: Mapped[User] = relationship(back_populates="applications")
    predictions: Mapped[list[Prediction]] = relationship(back_populates="application")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    risk_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    detector_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    application: Mapped[Application | None] = relationship(back_populates="predictions")
    feedback_entries: Mapped[list[Feedback]] = relationship(back_populates="prediction")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    prediction_id: Mapped[str] = mapped_column(
        ForeignKey("predictions.id"), nullable=False, index=True
    )
    officer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    agreed_with_model: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    detector_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    prediction: Mapped[Prediction] = relationship(back_populates="feedback_entries")
    officer: Mapped[User] = relationship(back_populates="feedback_entries")


class ExplanationExperimentAssignment(Base):
    """One durable score-only or explanation-shown assignment per officer."""

    __tablename__ = "explanation_experiment_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    officer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class ExplanationExperimentExposure(Base):
    """An idempotent record that an assigned officer reached a scored review."""

    __tablename__ = "explanation_experiment_exposures"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "prediction_id", name="uq_experiment_exposure_assignment_prediction"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("explanation_experiment_assignments.id"), nullable=False, index=True
    )
    prediction_id: Mapped[str] = mapped_column(
        ForeignKey("predictions.id"), nullable=False, index=True
    )
    officer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    explanation_shown: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class MonitoringSnapshot(Base):
    """Persisted drift snapshots for a trendable, non-row-level monitoring history."""

    __tablename__ = "monitoring_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )


class RetrainingTicket(Base):
    """A logged human review request; it never invokes training or deployment."""

    __tablename__ = "retraining_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    monitoring_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("monitoring_snapshots.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    human_review_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

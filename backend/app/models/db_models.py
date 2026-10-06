"""PostgreSQL-native persistence models for auditable decision support."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
UUID_TYPE = UUID(as_uuid=False)
TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    """Base with deterministic names so Alembic diffs are stable."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    assigned_role: Mapped[Role | None] = relationship(back_populates="users")
    applications: Mapped[list[Application]] = relationship(back_populates="created_by")
    feedback_entries: Mapped[list[Feedback]] = relationship(back_populates="officer")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_created_by_id_created_at", "created_by_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128), index=True, nullable=True
    )
    raw_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    created_by: Mapped[User] = relationship(back_populates="applications")
    predictions: Mapped[list[Prediction]] = relationship(back_populates="application")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="score_probability"),
        CheckConstraint("threshold > 0 AND threshold < 1", name="threshold_probability"),
        Index("ix_predictions_created_at", "created_at"),
        Index("ix_predictions_requested_by_id_created_at", "requested_by_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    application_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    risk_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    detector_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    application: Mapped[Application | None] = relationship(back_populates="predictions")
    feedback_entries: Mapped[list[Feedback]] = relationship(back_populates="prediction")


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("prediction_id", "version", name="uq_feedback_prediction_version"),
        CheckConstraint(
            "decision IN ('approve', 'decline', 'escalate')",
            name="valid_decision",
        ),
        Index("ix_feedback_prediction_id_created_at", "prediction_id", "created_at"),
        Index("ix_feedback_officer_id_created_at", "officer_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    prediction_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    officer_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    amends_feedback_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("feedback.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agreed_with_model: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    detector_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    prediction: Mapped[Prediction] = relationship(back_populates="feedback_entries")
    officer: Mapped[User] = relationship(back_populates="feedback_entries")


class ExplanationExperimentAssignment(Base):
    __tablename__ = "explanation_experiment_assignments"
    __table_args__ = (
        CheckConstraint(
            "variant IN ('score_only', 'explanation_shown')",
            name="valid_variant",
        ),
        UniqueConstraint(
            "officer_id",
            name="uq_explanation_experiment_assignments_officer_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    officer_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )


class ExplanationExperimentExposure(Base):
    __tablename__ = "explanation_experiment_exposures"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "prediction_id", name="uq_experiment_exposure_assignment_prediction"
        ),
        CheckConstraint(
            "variant IN ('score_only', 'explanation_shown')",
            name="valid_variant",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    assignment_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("explanation_experiment_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prediction_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    officer_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    explanation_shown: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )


class MonitoringSnapshot(Base):
    __tablename__ = "monitoring_snapshots"
    __table_args__ = (
        CheckConstraint(
            "source IN ('score_observation', 'feature_drift')",
            name="valid_source",
        ),
        Index("ix_monitoring_snapshots_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )


class RetrainingTicket(Base):
    __tablename__ = "retraining_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'approved', 'rejected')",
            name="valid_status",
        ),
        Index("ix_retraining_tickets_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    monitoring_snapshot_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("monitoring_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    human_review_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default=text("'open'"), index=True
    )
    requested_by_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reviewed_by_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    users: Mapped[list[User]] = relationship(back_populates="assigned_role")
    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    roles: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[str] = mapped_column(
        UUID_TYPE,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(back_populates="roles")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(
        UUID_TYPE, primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(UUID_TYPE, nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

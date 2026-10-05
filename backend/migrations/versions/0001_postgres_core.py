"""Create the PostgreSQL-native application schema.

Revision ID: 0001_postgres_core
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_postgres_core"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True)
UUID_DEFAULT = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "role IN ('loan_officer', 'risk_analyst', 'admin')",
            name="valid_legacy_role",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "applications",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("external_reference", sa.String(128), nullable=True),
        sa.Column("raw_features", JSONB, nullable=False),
        sa.Column("created_by_id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_applications_created_by_id_users", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
    )
    op.create_index("ix_applications_created_by_id", "applications", ["created_by_id"])
    op.create_index(
        "ix_applications_created_by_id_created_at",
        "applications",
        ["created_by_id", "created_at"],
    )
    op.create_index(
        "ix_applications_external_reference", "applications", ["external_reference"]
    )

    op.create_table(
        "predictions",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("application_id", UUID, nullable=True),
        sa.Column("requested_by_id", UUID, nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("risk_flag", sa.Boolean(), nullable=False),
        sa.Column("explanation", JSONB, nullable=False),
        sa.Column("detector_state", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1", name="score_probability"
        ),
        sa.CheckConstraint(
            "threshold > 0 AND threshold < 1",
            name="threshold_probability",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"],
            name="fk_predictions_application_id_applications", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"],
            name="fk_predictions_requested_by_id_users", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_predictions"),
    )
    op.create_index("ix_predictions_application_id", "predictions", ["application_id"])
    op.create_index("ix_predictions_created_at", "predictions", ["created_at"])
    op.create_index("ix_predictions_requested_by_id", "predictions", ["requested_by_id"])
    op.create_index(
        "ix_predictions_requested_by_id_created_at",
        "predictions",
        ["requested_by_id", "created_at"],
    )

    op.create_table(
        "feedback",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("prediction_id", UUID, nullable=False),
        sa.Column("officer_id", UUID, nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("agreed_with_model", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("detector_state", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve', 'decline', 'escalate')",
            name="valid_decision",
        ),
        sa.ForeignKeyConstraint(
            ["officer_id"], ["users.id"],
            name="fk_feedback_officer_id_users", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"], ["predictions.id"],
            name="fk_feedback_prediction_id_predictions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.UniqueConstraint("prediction_id", name="uq_feedback_prediction"),
    )
    op.create_index("ix_feedback_officer_id", "feedback", ["officer_id"])
    op.create_index("ix_feedback_prediction_id", "feedback", ["prediction_id"])

    op.create_table(
        "explanation_experiment_assignments",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("officer_id", UUID, nullable=False),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "variant IN ('score_only', 'explanation_shown')",
            name="valid_variant",
        ),
        sa.ForeignKeyConstraint(
            ["officer_id"], ["users.id"],
            name="fk_explanation_experiment_assignments_officer_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_explanation_experiment_assignments"),
        sa.UniqueConstraint(
            "officer_id", name="uq_explanation_experiment_assignments_officer_id"
        ),
    )
    op.create_index(
        "ix_explanation_experiment_assignments_officer_id",
        "explanation_experiment_assignments",
        ["officer_id"],
    )
    op.create_index(
        "ix_explanation_experiment_assignments_variant",
        "explanation_experiment_assignments",
        ["variant"],
    )

    op.create_table(
        "explanation_experiment_exposures",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("assignment_id", UUID, nullable=False),
        sa.Column("prediction_id", UUID, nullable=False),
        sa.Column("officer_id", UUID, nullable=False),
        sa.Column("variant", sa.String(32), nullable=False),
        sa.Column("explanation_shown", sa.Boolean(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "variant IN ('score_only', 'explanation_shown')",
            name="valid_variant",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["explanation_experiment_assignments.id"],
            name="fk_exposure_assignment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["officer_id"], ["users.id"],
            name="fk_explanation_experiment_exposures_officer_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"], ["predictions.id"],
            name="fk_explanation_experiment_exposures_prediction_id_predictions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_explanation_experiment_exposures"),
        sa.UniqueConstraint(
            "assignment_id", "prediction_id",
            name="uq_experiment_exposure_assignment_prediction",
        ),
    )
    for column in ("assignment_id", "officer_id", "prediction_id", "variant"):
        op.create_index(
            f"ix_explanation_experiment_exposures_{column}",
            "explanation_experiment_exposures",
            [column],
        )

    op.create_table(
        "monitoring_snapshots",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "source IN ('score_observation', 'feature_drift')",
            name="valid_source",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_monitoring_snapshots"),
    )
    op.create_index(
        "ix_monitoring_snapshots_created_at", "monitoring_snapshots", ["created_at"]
    )
    op.create_index("ix_monitoring_snapshots_source", "monitoring_snapshots", ["source"])
    op.create_index("ix_monitoring_snapshots_status", "monitoring_snapshots", ["status"])

    op.create_table(
        "retraining_tickets",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("monitoring_snapshot_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("human_review_confirmed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), server_default=sa.text("'open'"), nullable=False),
        sa.Column("requested_by_id", UUID, nullable=False),
        sa.Column("reviewed_by_id", UUID, nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.Column("reviewed_at", TIMESTAMPTZ, nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'approved', 'rejected')",
            name="valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["monitoring_snapshot_id"], ["monitoring_snapshots.id"],
            name="fk_retraining_ticket_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"],
            name="fk_retraining_tickets_requested_by_id_users", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"],
            name="fk_retraining_tickets_reviewed_by_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retraining_tickets"),
    )
    for column in ("created_at", "monitoring_snapshot_id", "requested_by_id", "status"):
        op.create_index(
            f"ix_retraining_tickets_{column}", "retraining_tickets", [column]
        )


def downgrade() -> None:
    op.drop_table("retraining_tickets")
    op.drop_table("monitoring_snapshots")
    op.drop_table("explanation_experiment_exposures")
    op.drop_table("explanation_experiment_assignments")
    op.drop_table("feedback")
    op.drop_table("predictions")
    op.drop_table("applications")
    op.drop_table("users")

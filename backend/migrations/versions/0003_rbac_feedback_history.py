"""Finalize RBAC and make feedback an append-only history.

Revision ID: 0003_rbac_feedback_history
Revises: 0002_rbac_audit_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_rbac_feedback_history"
down_revision = "0002_rbac_audit_schema"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    # Role rows must exist before legacy users can be data-migrated. The seed
    # later updates descriptions and synchronizes the permission catalogue.
    op.execute(
        """
        INSERT INTO roles (name, description, is_system)
        VALUES
          ('loan_officer', 'Creates and reviews their own loan applications.', true),
          ('risk_analyst', 'Reviews portfolio risk, drift, models, and retraining tickets.', true),
          ('admin', 'Administers users and audits and reviews retraining tickets.', true)
        ON CONFLICT (name) DO UPDATE
        SET description = EXCLUDED.description, is_system = true
        """
    )
    op.execute(
        """
        UPDATE users AS users
        SET role_id = roles.id
        FROM roles
        WHERE users.role_id IS NULL AND roles.name = users.role
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM users WHERE role_id IS NULL) THEN
            RAISE EXCEPTION 'Cannot finalize RBAC: one or more users have an unknown legacy role';
          END IF;
        END $$
        """
    )
    op.alter_column("users", "role_id", existing_type=UUID, nullable=False)
    op.drop_index("ix_users_role", table_name="users")
    op.drop_constraint(op.f("ck_users_valid_legacy_role"), "users", type_="check")
    op.drop_column("users", "role")

    op.drop_constraint("uq_feedback_prediction", "feedback", type_="unique")
    op.add_column(
        "feedback",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("feedback", sa.Column("amends_feedback_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_feedback_amends_feedback_id_feedback",
        "feedback",
        "feedback",
        ["amends_feedback_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_feedback_amends_feedback_id", "feedback", ["amends_feedback_id"])
    op.create_index(
        "ix_feedback_prediction_id_created_at", "feedback", ["prediction_id", "created_at"]
    )
    op.create_index(
        "ix_feedback_officer_id_created_at", "feedback", ["officer_id", "created_at"]
    )
    op.create_unique_constraint(
        "uq_feedback_prediction_version", "feedback", ["prediction_id", "version"]
    )
    op.alter_column(
        "audit_events",
        "metadata",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_events",
        "metadata",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        server_default=None,
        existing_nullable=False,
    )
    op.drop_constraint("uq_feedback_prediction_version", "feedback", type_="unique")
    op.drop_index("ix_feedback_officer_id_created_at", table_name="feedback")
    op.drop_index("ix_feedback_prediction_id_created_at", table_name="feedback")
    op.drop_index("ix_feedback_amends_feedback_id", table_name="feedback")
    op.drop_constraint("fk_feedback_amends_feedback_id_feedback", "feedback", type_="foreignkey")
    op.execute(
        """
        DELETE FROM feedback
        WHERE id NOT IN (
          SELECT DISTINCT ON (prediction_id) id
          FROM feedback
          ORDER BY prediction_id, version DESC, created_at DESC, id DESC
        )
        """
    )
    op.drop_column("feedback", "amends_feedback_id")
    op.drop_column("feedback", "version")
    op.create_unique_constraint("uq_feedback_prediction", "feedback", ["prediction_id"])

    op.add_column("users", sa.Column("role", sa.String(32), nullable=True))
    op.execute(
        """
        UPDATE users AS users
        SET role = roles.name
        FROM roles
        WHERE roles.id = users.role_id
        """
    )
    op.alter_column("users", "role", existing_type=sa.String(32), nullable=False)
    op.create_check_constraint(
        op.f("ck_users_valid_legacy_role"),
        "users",
        "role IN ('loan_officer', 'risk_analyst', 'admin')",
    )
    op.create_index("ix_users_role", "users", ["role"])

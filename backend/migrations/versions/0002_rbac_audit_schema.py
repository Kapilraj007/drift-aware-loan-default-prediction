"""Add the RBAC catalogue, user security fields, and audit-event schema.

Revision ID: 0002_rbac_audit_schema
Revises: 0001_postgres_core

Phase 4 will seed the catalogue, data-migrate users, and make role_id
authoritative. It remains nullable in Phase 3 so current authorization behavior
is preserved during the schema transition.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_rbac_audit_schema"
down_revision = "0001_postgres_core"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True)
UUID_DEFAULT = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("permission_id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"],
            name="fk_role_permissions_role_id_roles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )

    op.add_column("users", sa.Column("role_id", UUID, nullable=True))
    op.add_column("users", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("users", sa.Column("full_name", sa.String(200), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("last_login_at", TIMESTAMPTZ, nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("users", sa.Column("locked_until", TIMESTAMPTZ, nullable=True))
    op.create_foreign_key(
        "fk_users_role_id_roles",
        "users",
        "roles",
        ["role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, server_default=UUID_DEFAULT, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", UUID, nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
    for column in (
        "locked_until",
        "failed_login_count",
        "last_login_at",
        "must_change_password",
        "full_name",
        "email",
        "role_id",
    ):
        op.drop_column("users", column)
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")

"""Initial isolated Keyholder schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backends",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("config_ref", sa.String(64), nullable=False),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'revoked')", name="ck_customer_status"
        ),
    )
    op.create_index("ix_customers_token_hash", "customers", ["token_hash"], unique=True)
    op.create_table(
        "customer_mappings",
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("backend_id", sa.String(64), sa.ForeignKey("backends.id"), nullable=False),
        sa.Column("upstream_username", sa.String(32), nullable=False),
    )
    op.create_table(
        "application_data",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    backend = sa.table(
        "backends",
        sa.column("id", sa.String),
        sa.column("provider", sa.String),
        sa.column("config_ref", sa.String),
    )
    op.bulk_insert(
        backend, [{"id": "marzban-default", "provider": "marzban", "config_ref": "default"}]
    )


def downgrade() -> None:
    op.drop_table("application_data")
    op.drop_table("customer_mappings")
    op.drop_index("ix_customers_token_hash", "customers")
    op.drop_table("customers")
    op.drop_table("backends")

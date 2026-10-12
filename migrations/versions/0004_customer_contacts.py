"""Add minimal private customer contact metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("telegram", sa.String(64), nullable=True))
    op.add_column("customers", sa.Column("phone", sa.String(16), nullable=True))
    op.create_index(
        "uq_customers_telegram",
        "customers",
        [sa.text("telegram COLLATE NOCASE")],
        unique=True,
        sqlite_where=sa.text("telegram IS NOT NULL"),
    )
    op.create_index(
        "uq_customers_phone",
        "customers",
        ["phone"],
        unique=True,
        sqlite_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_customers_phone", table_name="customers")
    op.drop_index("uq_customers_telegram", table_name="customers")
    op.drop_column("customers", "phone")
    op.drop_column("customers", "telegram")

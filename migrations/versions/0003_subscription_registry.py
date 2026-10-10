"""Canonical registration and encrypted tokens; legacy rows/hashes preserved."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("token_encrypted", sa.String(512), nullable=True))
    op.create_table(
        "registrations",
        sa.Column("backend_id", sa.String(64), sa.ForeignKey("backends.id"), primary_key=True),
        sa.Column("upstream_username", sa.String(32), primary_key=True),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False, unique=True
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT m.backend_id,m.upstream_username,c.id FROM customers c "
            "JOIN customer_mappings m ON m.customer_id=c.id WHERE c.status!='revoked' "
            "ORDER BY c.created_at,c.id"
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["backend_id"], row["upstream_username"])
        if key in seen:
            continue
        seen.add(key)
        bind.execute(
            sa.text("INSERT INTO registrations VALUES (:b,:u,:c)"),
            {"b": key[0], "u": key[1], "c": row["id"]},
        )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM customers WHERE token_encrypted IS NOT NULL"))
        .scalar_one()
    )
    if count:
        raise RuntimeError("Restore reviewed backup; token vault data must not be discarded")
    op.drop_table("registrations")
    op.drop_column("customers", "token_encrypted")

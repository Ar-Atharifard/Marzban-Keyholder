"""Archive policies and enable all five profiles, preserving identities and credentials."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen historical contract: do not import live application policy defaults here.
ALL_PROFILES = ["tcp_reality", "xhttp_reality", "grpc_cdn", "tcp_reality_ipv6", "shadowsocks_ipv6"]


def normalize_policy(value: object) -> dict[str, list[str]]:
    # Owner approved enabling all five for existing customers on October 10, 2026.
    # Status, identity, credentials and upstream protocol permissions are unchanged.
    return {"profiles": list(ALL_PROFILES)}


def tables() -> tuple[sa.TableClause, sa.TableClause]:
    customers = sa.table("customers", sa.column("id", sa.String), sa.column("policy", sa.JSON))
    archive = sa.table(
        "application_data",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    return customers, archive


def upgrade() -> None:
    bind = op.get_bind()
    customers, archive = tables()
    # Entire data migration participates in Alembic's transaction; no schema/data deletion.
    for row in bind.execute(sa.select(customers.c.id, customers.c.policy)).mappings().all():
        key = "policy-0002:" + row["id"]
        existing = bind.execute(
            sa.select(archive.c.value).where(archive.c.key == key)
        ).scalar_one_or_none()
        if existing is not None:
            continue
        new = normalize_policy(row["policy"])
        bind.execute(
            archive.insert().values(
                key=key,
                value={"original": row["policy"], "applied": new},
                updated_at=datetime.now(UTC),
            )
        )
        bind.execute(customers.update().where(customers.c.id == row["id"]).values(policy=new))


def downgrade() -> None:
    bind = op.get_bind()
    customers, archive = tables()
    rows = (
        bind.execute(
            sa.select(archive.c.key, archive.c.value).where(archive.c.key.like("policy-0002:%"))
        )
        .mappings()
        .all()
    )
    # Preflight every row before restoration; never overwrite subsequent admin changes.
    for row in rows:
        cid = row["key"].removeprefix("policy-0002:")
        current = bind.execute(
            sa.select(customers.c.policy).where(customers.c.id == cid)
        ).scalar_one_or_none()
        if current is not None and current != row["value"]["applied"]:
            raise RuntimeError(
                "Policy changed after migration; use reviewed backup restore for rollback"
            )
    for row in rows:
        cid = row["key"].removeprefix("policy-0002:")
        bind.execute(
            customers.update().where(customers.c.id == cid).values(policy=row["value"]["original"])
        )
        bind.execute(archive.delete().where(archive.c.key == row["key"]))

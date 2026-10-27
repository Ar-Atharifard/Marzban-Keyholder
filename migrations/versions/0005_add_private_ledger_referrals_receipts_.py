"""Add private ledger referrals receipts and storage budgets"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_actions",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        op.f("ix_billing_actions_created_at"), "billing_actions", ["created_at"], unique=False
    )
    op.create_table(
        "storage_reservations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("temporary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_storage_reservations_scope"), "storage_reservations", ["scope"], unique=False
    )
    op.create_table(
        "storage_usage",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("receiving_account", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("currency = 'IRR'", name="ck_payment_currency"),
        sa.CheckConstraint("status IN ('pending','confirmed','void')", name="ck_payment_status"),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_amount"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_customer_id"), "payments", ["customer_id"], unique=False)
    op.create_index(op.f("ix_payments_received_at"), "payments", ["received_at"], unique=False)
    op.create_index(
        "uq_payment_reference",
        "payments",
        ["receiving_account", "reference"],
        unique=True,
        sqlite_where=sa.text("reference IS NOT NULL AND status != 'void'"),
    )
    op.create_table(
        "purchases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=1000), nullable=True),
        sa.CheckConstraint("currency IN ('IRR','USDT','LTC')", name="ck_purchase_currency"),
        sa.CheckConstraint("price_minor >= 0", name="ck_purchase_price"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchases_customer_id"), "purchases", ["customer_id"], unique=False)
    op.create_index(op.f("ix_purchases_purchased_at"), "purchases", ["purchased_at"], unique=False)
    op.create_table(
        "referral_gifts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("referrer_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("referral_ids", sa.JSON(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["referrer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_referral_gifts_referrer_id"), "referral_gifts", ["referrer_id"], unique=False
    )
    op.create_table(
        "customer_referrals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("referrer_id", sa.String(length=36), nullable=False),
        sa.Column("introduced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gift_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("customer_id != referrer_id", name="ck_referral_self"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["gift_id"],
            ["referral_gifts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["referrer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(
        op.f("ix_customer_referrals_gift_id"), "customer_referrals", ["gift_id"], unique=False
    )
    op.create_index(
        op.f("ix_customer_referrals_introduced_at"),
        "customer_referrals",
        ["introduced_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_referrals_referrer_id"),
        "customer_referrals",
        ["referrer_id"],
        unique=False,
    )
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("purchase_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name="ck_allocation_amount"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_allocations_payment_id"),
        "payment_allocations",
        ["payment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_allocations_purchase_id"),
        "payment_allocations",
        ["purchase_id"],
        unique=False,
    )
    op.create_table(
        "payment_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("object_key", sa.String(length=128), nullable=False),
        sa.Column("version_id", sa.String(length=256), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("keep", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "state IN ('uploading','available','failed','deleting','expired')",
            name="ck_receipt_state",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_receipt_size"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        op.f("ix_payment_receipts_created_at"), "payment_receipts", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_payment_receipts_payment_id"), "payment_receipts", ["payment_id"], unique=False
    )
    op.create_index(op.f("ix_payment_receipts_state"), "payment_receipts", ["state"], unique=False)
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_refund_amount"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_refunds_payment_id"), "payment_refunds", ["payment_id"], unique=False
    )


def downgrade() -> None:
    for name in (
        "billing_actions",
        "payments",
        "purchases",
        "payment_allocations",
        "payment_refunds",
        "customer_referrals",
        "referral_gifts",
        "payment_receipts",
    ):
        if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {name}")):
            raise RuntimeError(
                "Ledger history exists; restore a reviewed pre-migration backup "
                "instead of dropping financial records"
            )
    op.drop_index(op.f("ix_payment_refunds_payment_id"), table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index(op.f("ix_payment_receipts_state"), table_name="payment_receipts")
    op.drop_index(op.f("ix_payment_receipts_payment_id"), table_name="payment_receipts")
    op.drop_index(op.f("ix_payment_receipts_created_at"), table_name="payment_receipts")
    op.drop_table("payment_receipts")
    op.drop_index(op.f("ix_payment_allocations_purchase_id"), table_name="payment_allocations")
    op.drop_index(op.f("ix_payment_allocations_payment_id"), table_name="payment_allocations")
    op.drop_table("payment_allocations")
    op.drop_index(op.f("ix_customer_referrals_referrer_id"), table_name="customer_referrals")
    op.drop_index(op.f("ix_customer_referrals_introduced_at"), table_name="customer_referrals")
    op.drop_index(op.f("ix_customer_referrals_gift_id"), table_name="customer_referrals")
    op.drop_table("customer_referrals")
    op.drop_index(op.f("ix_referral_gifts_referrer_id"), table_name="referral_gifts")
    op.drop_table("referral_gifts")
    op.drop_index(op.f("ix_purchases_purchased_at"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_customer_id"), table_name="purchases")
    op.drop_table("purchases")
    op.drop_index(op.f("ix_payments_received_at"), table_name="payments")
    op.drop_index(op.f("ix_payments_customer_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_table("storage_usage")
    op.drop_index(op.f("ix_storage_reservations_scope"), table_name="storage_reservations")
    op.drop_table("storage_reservations")
    op.drop_index(op.f("ix_billing_actions_created_at"), table_name="billing_actions")
    op.drop_table("billing_actions")

"""add billing subscriptions and invoices"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260319_0010"
down_revision: str | None = "20260319_0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_subscriptions",
        sa.Column("auth_user_id", sa.String(length=255), nullable=False),
        sa.Column("auth_provider", sa.String(length=50), nullable=True),
        sa.Column("provider", sa.Enum("razorpay", name="billingprovider", native_enum=False), nullable=False),
        sa.Column(
            "plan_code",
            sa.Enum(
                "free",
                "advocate_pro",
                "chamber_pro",
                name="billingplancode",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "free",
                "checkout_pending",
                "active",
                "past_due",
                "cancelled",
                "expired",
                name="billingsubscriptionstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_customer_id", sa.String(length=255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("provider_plan_id", sa.String(length=255), nullable=True),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("daily_query_limit", sa.Integer(), nullable=True),
        sa.Column("max_active_workspaces", sa.Integer(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("last_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_subscriptions")),
    )
    op.create_index(
        op.f("ix_billing_subscriptions_auth_user_id"),
        "billing_subscriptions",
        ["auth_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_billing_subscriptions_provider_subscription_id"),
        "billing_subscriptions",
        ["provider_subscription_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_billing_subscriptions_status"),
        "billing_subscriptions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "billing_invoices",
        sa.Column("auth_user_id", sa.String(length=255), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.Enum("razorpay", name="billingprovider", native_enum=False), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=255), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "issued",
                "paid",
                "failed",
                "refunded",
                name="billinginvoicestatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_url", sa.String(length=1000), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["billing_subscriptions.id"],
            name=op.f("fk_billing_invoices_subscription_id_billing_subscriptions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_invoices")),
    )
    op.create_index(
        op.f("ix_billing_invoices_auth_user_id"),
        "billing_invoices",
        ["auth_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_billing_invoices_provider_invoice_id"),
        "billing_invoices",
        ["provider_invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_billing_invoices_status"),
        "billing_invoices",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_billing_invoices_subscription_id"),
        "billing_invoices",
        ["subscription_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_billing_invoices_subscription_id"), table_name="billing_invoices")
    op.drop_index(op.f("ix_billing_invoices_status"), table_name="billing_invoices")
    op.drop_index(op.f("ix_billing_invoices_provider_invoice_id"), table_name="billing_invoices")
    op.drop_index(op.f("ix_billing_invoices_auth_user_id"), table_name="billing_invoices")
    op.drop_table("billing_invoices")

    op.drop_index(
        op.f("ix_billing_subscriptions_status"),
        table_name="billing_subscriptions",
    )
    op.drop_index(
        op.f("ix_billing_subscriptions_provider_subscription_id"),
        table_name="billing_subscriptions",
    )
    op.drop_index(
        op.f("ix_billing_subscriptions_auth_user_id"),
        table_name="billing_subscriptions",
    )
    op.drop_table("billing_subscriptions")

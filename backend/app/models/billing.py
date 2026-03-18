from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONPayloadMixin, TimestampMixin, UUIDPrimaryKeyMixin


class BillingProvider(StrEnum):
    RAZORPAY = "razorpay"


class BillingPlanCode(StrEnum):
    FREE = "free"
    ADVOCATE_PRO = "advocate_pro"
    CHAMBER_PRO = "chamber_pro"


class BillingSubscriptionStatus(StrEnum):
    FREE = "free"
    CHECKOUT_PENDING = "checkout_pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingInvoiceStatus(StrEnum):
    ISSUED = "issued"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class BillingSubscription(UUIDPrimaryKeyMixin, TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "billing_subscriptions"

    auth_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    auth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider: Mapped[BillingProvider] = mapped_column(
        Enum(BillingProvider, native_enum=False),
        nullable=False,
        default=BillingProvider.RAZORPAY,
    )
    plan_code: Mapped[BillingPlanCode] = mapped_column(
        Enum(BillingPlanCode, native_enum=False),
        nullable=False,
    )
    status: Mapped[BillingSubscriptionStatus] = mapped_column(
        Enum(BillingSubscriptionStatus, native_enum=False),
        nullable=False,
        default=BillingSubscriptionStatus.CHECKOUT_PENDING,
        index=True,
    )
    provider_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    provider_plan_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    daily_query_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_active_workspaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingInvoice(UUIDPrimaryKeyMixin, TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "billing_invoices"

    auth_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[BillingProvider] = mapped_column(
        Enum(BillingProvider, native_enum=False),
        nullable=False,
        default=BillingProvider.RAZORPAY,
    )
    provider_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="INR")
    status: Mapped[BillingInvoiceStatus] = mapped_column(
        Enum(BillingInvoiceStatus, native_enum=False),
        nullable=False,
        default=BillingInvoiceStatus.ISSUED,
        index=True,
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

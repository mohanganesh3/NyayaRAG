from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import (
    BillingInvoiceStatus,
    BillingPlanCode,
    BillingProvider,
    BillingSubscriptionStatus,
)


class BillingPlanDefinitionRead(BaseModel):
    code: BillingPlanCode
    name: str
    price_minor: int
    currency: str
    cadence: str
    daily_query_limit: int | None = None
    workspace_access: bool
    max_active_workspaces: int | None = None
    included_seats: int
    features: list[str]
    razorpay_plan_id: str | None = None


class BillingPlansResponse(BaseModel):
    success: Literal[True] = True
    data: list[BillingPlanDefinitionRead]


class BillingSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_code: BillingPlanCode
    plan_name: str
    provider: BillingProvider
    status: BillingSubscriptionStatus
    price_minor: int
    currency: str
    cadence: str
    daily_query_limit: int | None = None
    workspace_access: bool
    max_active_workspaces: int | None = None
    included_seats: int
    queries_used_today: int
    queries_remaining_today: int | None = None
    provider_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


class BillingSubscriptionResponse(BaseModel):
    success: Literal[True] = True
    data: BillingSubscriptionRead


class BillingInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    auth_user_id: str
    subscription_id: str | None = None
    provider: BillingProvider
    provider_invoice_id: str | None = None
    amount_minor: int
    currency: str
    status: BillingInvoiceStatus
    period_start: datetime | None = None
    period_end: datetime | None = None
    issued_at: datetime | None = None
    paid_at: datetime | None = None
    receipt_url: str | None = None
    description: str | None = None
    created_at: datetime


class BillingHistoryResponse(BaseModel):
    success: Literal[True] = True
    data: list[BillingInvoiceRead]


class BillingCheckoutRequest(BaseModel):
    plan_code: BillingPlanCode


class BillingCheckoutData(BaseModel):
    provider: BillingProvider
    plan_code: BillingPlanCode
    plan_name: str
    provider_plan_id: str | None = None
    provider_subscription_id: str
    checkout_url: str


class BillingCheckoutResponse(BaseModel):
    success: Literal[True] = True
    data: BillingCheckoutData

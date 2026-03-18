from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.core.config import get_settings
from app.models import (
    BillingInvoice,
    BillingInvoiceStatus,
    BillingPlanCode,
    BillingProvider,
    BillingSubscription,
    BillingSubscriptionStatus,
    QueryHistoryEntry,
)
from app.schemas.billing import BillingSubscriptionRead
from sqlalchemy import func, select
from sqlalchemy.orm import Session

settings = get_settings()


@dataclass(frozen=True, slots=True)
class BillingPlanDefinition:
    code: BillingPlanCode
    name: str
    price_minor: int
    currency: str
    cadence: str
    daily_query_limit: int | None
    workspace_access: bool
    max_active_workspaces: int | None
    included_seats: int
    features: tuple[str, ...]
    razorpay_plan_id: str | None


@dataclass(frozen=True, slots=True)
class QueryAllowanceDecision:
    allowed: bool
    code: str | None
    detail: dict[str, object]
    message: str | None
    status_code: int | None


PLAN_CATALOG: dict[BillingPlanCode, BillingPlanDefinition] = {
    BillingPlanCode.FREE: BillingPlanDefinition(
        code=BillingPlanCode.FREE,
        name="Free",
        price_minor=0,
        currency="INR",
        cadence="month",
        daily_query_limit=20,
        workspace_access=False,
        max_active_workspaces=None,
        included_seats=1,
        features=(
            "20 queries per day",
            "Supreme Court + High Courts",
            "Basic citation verification",
            "No document upload",
        ),
        razorpay_plan_id=None,
    ),
    BillingPlanCode.ADVOCATE_PRO: BillingPlanDefinition(
        code=BillingPlanCode.ADVOCATE_PRO,
        name="Advocate Pro",
        price_minor=79900,
        currency="INR",
        cadence="month",
        daily_query_limit=None,
        workspace_access=True,
        max_active_workspaces=5,
        included_seats=1,
        features=(
            "Unlimited queries",
            "All courts + tribunals + bare acts",
            "Upload up to 5 live case workspaces",
            "Citation graph and export workflow",
        ),
        razorpay_plan_id=settings.razorpay_plan_id_advocate_pro,
    ),
    BillingPlanCode.CHAMBER_PRO: BillingPlanDefinition(
        code=BillingPlanCode.CHAMBER_PRO,
        name="Chamber Pro",
        price_minor=249900,
        currency="INR",
        cadence="month",
        daily_query_limit=None,
        workspace_access=True,
        max_active_workspaces=25,
        included_seats=5,
        features=(
            "5 seats included",
            "Shared research workspaces",
            "Priority support",
            "API access and team history",
        ),
        razorpay_plan_id=settings.razorpay_plan_id_chamber_pro,
    ),
}

ACTIVE_BILLING_STATUSES = {
    BillingSubscriptionStatus.ACTIVE,
}


class BillingStore:
    def list_plans(self) -> list[BillingPlanDefinition]:
        return list(PLAN_CATALOG.values())

    def get_plan(self, plan_code: BillingPlanCode) -> BillingPlanDefinition:
        return PLAN_CATALOG[plan_code]

    def get_subscription(
        self,
        session: Session,
        *,
        auth_user_id: str,
    ) -> BillingSubscription | None:
        statement = (
            select(BillingSubscription)
            .where(BillingSubscription.auth_user_id == auth_user_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        return session.scalar(statement)

    def resolve_subscription(
        self,
        session: Session,
        *,
        auth_user_id: str,
        provider: BillingProvider = BillingProvider.RAZORPAY,
    ) -> BillingSubscriptionRead:
        subscription = self.get_subscription(session, auth_user_id=auth_user_id)
        plan = self.get_plan(
            subscription.plan_code if subscription is not None else BillingPlanCode.FREE
        )
        queries_used_today = self.count_queries_today(session, auth_user_id=auth_user_id)

        status = (
            subscription.status
            if subscription is not None
            else BillingSubscriptionStatus.FREE
        )
        provider_value = subscription.provider if subscription is not None else provider
        queries_remaining = (
            None
            if plan.daily_query_limit is None
            else max(plan.daily_query_limit - queries_used_today, 0)
        )

        return BillingSubscriptionRead(
            plan_code=plan.code,
            plan_name=plan.name,
            provider=provider_value,
            status=status,
            price_minor=plan.price_minor,
            currency=plan.currency,
            cadence=plan.cadence,
            daily_query_limit=plan.daily_query_limit,
            workspace_access=plan.workspace_access and status in ACTIVE_BILLING_STATUSES,
            max_active_workspaces=plan.max_active_workspaces,
            included_seats=plan.included_seats,
            queries_used_today=queries_used_today,
            queries_remaining_today=queries_remaining,
            provider_subscription_id=(
                subscription.provider_subscription_id if subscription is not None else None
            ),
            current_period_start=(
                subscription.current_period_start if subscription is not None else None
            ),
            current_period_end=(
                subscription.current_period_end if subscription is not None else None
            ),
            cancel_at_period_end=(
                subscription.cancel_at_period_end if subscription is not None else False
            ),
        )

    def evaluate_query_allowance(
        self,
        session: Session,
        *,
        auth_user_id: str | None,
        workspace_id: str | None,
    ) -> QueryAllowanceDecision:
        if auth_user_id is None:
            return QueryAllowanceDecision(
                allowed=True,
                code=None,
                message=None,
                status_code=None,
                detail={"plan_code": BillingPlanCode.FREE.value, "anonymous_preview": True},
            )

        subscription = self.resolve_subscription(session, auth_user_id=auth_user_id)
        if workspace_id is not None and not subscription.workspace_access:
            return QueryAllowanceDecision(
                allowed=False,
                code="plan_upgrade_required",
                message="Workspace research requires an active paid plan.",
                status_code=403,
                detail={
                    "plan_code": subscription.plan_code.value,
                    "workspace_id": workspace_id,
                    "required_plan": BillingPlanCode.ADVOCATE_PRO.value,
                },
            )

        if (
            subscription.daily_query_limit is not None
            and subscription.queries_used_today >= subscription.daily_query_limit
        ):
            return QueryAllowanceDecision(
                allowed=False,
                code="free_tier_limit_reached",
                message="The daily free-tier query limit has been reached.",
                status_code=429,
                detail={
                    "plan_code": subscription.plan_code.value,
                    "daily_query_limit": subscription.daily_query_limit,
                    "queries_used_today": subscription.queries_used_today,
                },
            )

        return QueryAllowanceDecision(
            allowed=True,
            code=None,
            message=None,
            status_code=None,
            detail={
                "plan_code": subscription.plan_code.value,
                "queries_remaining_today": subscription.queries_remaining_today,
                "workspace_access": subscription.workspace_access,
            },
        )

    def create_checkout(
        self,
        session: Session,
        *,
        auth_user_id: str,
        auth_provider: str | None,
        plan_code: BillingPlanCode,
    ) -> BillingSubscription:
        if plan_code is BillingPlanCode.FREE:
            raise ValueError("Free plan does not require checkout.")

        plan = self.get_plan(plan_code)
        subscription = BillingSubscription(
            auth_user_id=auth_user_id,
            auth_provider=auth_provider,
            provider=BillingProvider.RAZORPAY,
            plan_code=plan_code,
            status=BillingSubscriptionStatus.CHECKOUT_PENDING,
            provider_subscription_id=f"rzp_sub_preview_{uuid4().hex[:12]}",
            provider_plan_id=plan.razorpay_plan_id,
            seats=plan.included_seats,
            daily_query_limit=plan.daily_query_limit,
            max_active_workspaces=plan.max_active_workspaces,
        )
        session.add(subscription)
        session.flush()
        return subscription

    def upsert_subscription(
        self,
        session: Session,
        *,
        auth_user_id: str,
        plan_code: BillingPlanCode,
        status: BillingSubscriptionStatus,
        auth_provider: str | None = "clerk",
        provider_subscription_id: str | None = None,
        current_period_days: int = 30,
    ) -> BillingSubscription:
        plan = self.get_plan(plan_code)
        now = datetime.now(UTC)
        subscription = self.get_subscription(session, auth_user_id=auth_user_id)
        if subscription is None:
            subscription = BillingSubscription(
                auth_user_id=auth_user_id,
                auth_provider=auth_provider,
                provider=BillingProvider.RAZORPAY,
                plan_code=plan_code,
                status=status,
            )
            session.add(subscription)

        subscription.plan_code = plan_code
        subscription.status = status
        subscription.provider_plan_id = plan.razorpay_plan_id
        subscription.provider_subscription_id = (
            provider_subscription_id
            or subscription.provider_subscription_id
            or f"rzp_sub_active_{uuid4().hex[:12]}"
        )
        subscription.seats = plan.included_seats
        subscription.daily_query_limit = plan.daily_query_limit
        subscription.max_active_workspaces = plan.max_active_workspaces
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=current_period_days)
        subscription.cancel_at_period_end = False
        session.flush()
        return subscription

    def create_invoice(
        self,
        session: Session,
        *,
        auth_user_id: str,
        amount_minor: int,
        status: BillingInvoiceStatus,
        description: str,
        subscription_id: str | None = None,
        provider_invoice_id: str | None = None,
        receipt_url: str | None = None,
    ) -> BillingInvoice:
        invoice = BillingInvoice(
            auth_user_id=auth_user_id,
            subscription_id=subscription_id,
            provider=BillingProvider.RAZORPAY,
            provider_invoice_id=provider_invoice_id,
            amount_minor=amount_minor,
            currency="INR",
            status=status,
            issued_at=datetime.now(UTC),
            paid_at=datetime.now(UTC) if status is BillingInvoiceStatus.PAID else None,
            receipt_url=receipt_url,
            description=description,
        )
        session.add(invoice)
        session.flush()
        return invoice

    def list_invoices(
        self,
        session: Session,
        *,
        auth_user_id: str,
        limit: int = 20,
    ) -> list[BillingInvoice]:
        statement = (
            select(BillingInvoice)
            .where(BillingInvoice.auth_user_id == auth_user_id)
            .order_by(BillingInvoice.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def count_queries_today(
        self,
        session: Session,
        *,
        auth_user_id: str,
        reference_date: date | None = None,
    ) -> int:
        day = reference_date or datetime.now(UTC).date()
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        statement = select(func.count(QueryHistoryEntry.id)).where(
            QueryHistoryEntry.auth_user_id == auth_user_id,
            QueryHistoryEntry.created_at >= start,
            QueryHistoryEntry.created_at < end,
        )
        count = session.scalar(statement)
        return int(count or 0)


billing_store = BillingStore()

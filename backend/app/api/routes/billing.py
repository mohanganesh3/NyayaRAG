from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import AuthContext, require_auth_context
from app.db.session import get_db
from app.schemas.billing import (
    BillingCheckoutData,
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingHistoryResponse,
    BillingInvoiceRead,
    BillingPlanDefinitionRead,
    BillingPlansResponse,
    BillingSubscriptionResponse,
)
from app.services.billing import billing_store

router = APIRouter(tags=["billing"])
DbSession = Annotated[Session, Depends(get_db)]
RequiredAuth = Annotated[AuthContext, Depends(require_auth_context)]


@router.get("/billing/plans", response_model=BillingPlansResponse)
def list_billing_plans() -> BillingPlansResponse:
    return BillingPlansResponse(
        data=[
            BillingPlanDefinitionRead(
                code=plan.code,
                name=plan.name,
                price_minor=plan.price_minor,
                currency=plan.currency,
                cadence=plan.cadence,
                daily_query_limit=plan.daily_query_limit,
                workspace_access=plan.workspace_access,
                max_active_workspaces=plan.max_active_workspaces,
                included_seats=plan.included_seats,
                features=list(plan.features),
                razorpay_plan_id=plan.razorpay_plan_id,
            )
            for plan in billing_store.list_plans()
        ]
    )


@router.get("/billing/subscription", response_model=BillingSubscriptionResponse)
def get_subscription(
    db: DbSession,
    auth: RequiredAuth,
) -> BillingSubscriptionResponse:
    subscription = billing_store.resolve_subscription(
        db,
        auth_user_id=auth.user_id or "",
    )
    return BillingSubscriptionResponse(data=subscription)


@router.get("/billing/history", response_model=BillingHistoryResponse)
def get_billing_history(
    db: DbSession,
    auth: RequiredAuth,
) -> BillingHistoryResponse:
    invoices = billing_store.list_invoices(db, auth_user_id=auth.user_id or "")
    return BillingHistoryResponse(
        data=[BillingInvoiceRead.model_validate(invoice) for invoice in invoices]
    )


@router.post("/billing/checkout", response_model=BillingCheckoutResponse)
def create_checkout(
    request: BillingCheckoutRequest,
    db: DbSession,
    auth: RequiredAuth,
) -> BillingCheckoutResponse:
    if request.plan_code.value == "free":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "billing_checkout_invalid_plan",
                "message": "The free plan does not require a Razorpay checkout session.",
            },
        )

    subscription = billing_store.create_checkout(
        db,
        auth_user_id=auth.user_id or "",
        auth_provider=auth.provider,
        plan_code=request.plan_code,
    )
    db.commit()
    plan = billing_store.get_plan(request.plan_code)
    checkout_url = (
        "https://checkout.razorpay.com/v1/checkout.js"
        f"?plan_id={plan.razorpay_plan_id}&subscription_id={subscription.provider_subscription_id}"
    )

    return BillingCheckoutResponse(
        data=BillingCheckoutData(
            provider=subscription.provider,
            plan_code=request.plan_code,
            plan_name=plan.name,
            provider_plan_id=plan.razorpay_plan_id,
            provider_subscription_id=subscription.provider_subscription_id or "",
            checkout_url=checkout_url,
        )
    )

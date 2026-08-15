"""Billing endpoints (Phase 13 billing + Phase 14 subscriptions).

Read-only subscription/usage surfaces plus the Phase 14 checkout + subscription
report. All routes require a valid bearer credential with tenant role `owner`
or `admin` - a user access JWT or a `wc_*` API key (which always authenticates
as owner). Tenant scoping comes from the authenticated principal - the request
can never select another tenant's billing (00-AI-Development-Rules §7).

    GET  /api/billing/usage          live counts + monthly usage vs plan limits
    GET  /api/billing/plans          the purchasable subscription tiers
    POST /api/billing/checkout       start a hosted checkout for a plan upgrade
    GET  /api/billing/subscription   current subscription + payment history

Payment *activation* happens through the unauthenticated provider webhook at
`POST /api/webhooks/payment` (see `backend/api/routes/webhooks.py`) - this
router never accepts a payment claim from a caller.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import (
    billing_checkout_limiter,
    billing_limiter,
    current_principal,
    enforce_api_key_rate_limit,
    get_subscription_service,
    get_usage_service,
    require_principal_role,
)
from backend.core.config import get_settings
from backend.models.plan import PLANS, Plan, get_plan
from backend.models.subscription import Subscription
from backend.schemas.billing import (
    CheckoutOut,
    CheckoutRequest,
    PaymentOut,
    PlanLimitsOut,
    PlanOut,
    SubscriptionOut,
    SubscriptionReportOut,
    UsageCountsOut,
    UsageMetricOut,
    UsageOut,
)
from backend.services.api_keys import ApiKeyPrincipal
from backend.services.auth import Principal
from backend.services.billing import SubscriptionService, UsageService

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    dependencies=[Depends(require_principal_role("owner", "admin"))],
)


def _plan_out(plan: Plan, currency: str) -> PlanOut:
    return PlanOut(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        limits=PlanLimitsOut(
            max_websites=plan.max_websites,
            max_monthly_messages=plan.max_monthly_messages,
            max_monthly_tokens=plan.max_monthly_tokens,
            max_documents=plan.max_documents,
            max_crawl_pages=plan.max_crawl_pages,
        ),
        price_cents=plan.price_cents,
        currency=currency,
    )


def _subscription_out(subscription: Subscription, currency: str) -> SubscriptionOut:
    return SubscriptionOut(
        id=subscription.id,
        plan_id=subscription.plan_id,
        plan_name=get_plan(subscription.plan_id).name,
        status=subscription.status,
        payment_provider=subscription.payment_provider,
        payment_id=subscription.payment_id,
        start_date=subscription.start_date,
        end_date=subscription.end_date,
        created_at=subscription.created_at,
    )


def _payment_out(subscription: Subscription, currency: str) -> PaymentOut:
    plan = get_plan(subscription.plan_id)
    return PaymentOut(
        id=subscription.id,
        plan_id=subscription.plan_id,
        plan_name=plan.name,
        status=subscription.status,
        amount_cents=plan.price_cents,
        currency=currency,
        payment_provider=subscription.payment_provider,
        payment_id=subscription.payment_id,
        created_at=subscription.created_at,
    )


@router.get("/usage", response_model=UsageOut)
async def get_billing_usage(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[UsageService, Depends(get_usage_service)],
    _: Annotated[None, Depends(billing_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
) -> UsageOut:
    snapshot = await service.get_current_usage(principal.tenant_id)
    currency = get_settings().payment_currency
    return UsageOut(
        plan=_plan_out(snapshot.plan, currency),
        usage=UsageCountsOut(
            messages_sent=snapshot.totals.messages_sent,
            ai_responses=snapshot.totals.ai_responses,
            tokens_used=snapshot.totals.tokens_used,
            documents_created=snapshot.totals.documents_created,
            crawl_pages=snapshot.totals.crawl_pages,
            websites=snapshot.websites,
            documents=snapshot.documents,
        ),
        limits=[
            UsageMetricOut(
                metric=metric.metric,
                used=metric.used,
                limit=metric.limit,
                percent=metric.percent,
            )
            for metric in snapshot.metrics
        ],
    )


@router.get("/plans", response_model=list[PlanOut])
async def get_billing_plans(
    _: Annotated[None, Depends(billing_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
) -> list[PlanOut]:
    currency = get_settings().payment_currency
    return [_plan_out(plan, currency) for plan in PLANS.values()]


@router.post("/checkout", response_model=CheckoutOut, status_code=201)
async def create_billing_checkout(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    body: CheckoutRequest,
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
    _: Annotated[None, Depends(billing_checkout_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
) -> CheckoutOut:
    checkout = await service.create_checkout(
        tenant_id=principal.tenant_id,
        plan_id=body.plan_id,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    return CheckoutOut(checkout_id=checkout.checkout_id, url=checkout.url)


@router.get("/subscription", response_model=SubscriptionReportOut)
async def get_billing_subscription(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
    _: Annotated[None, Depends(billing_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
) -> SubscriptionReportOut:
    currency = get_settings().payment_currency
    current, history = await service.get_report(principal.tenant_id)
    return SubscriptionReportOut(
        subscription=(
            _subscription_out(current, currency) if current is not None else None
        ),
        payments=[_payment_out(subscription, currency) for subscription in history],
    )


__all__ = ["router"]

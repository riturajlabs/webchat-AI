'use client';

import Link from 'next/link';
import { Receipt } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { USAGE_LIMIT_LABELS, type PlanLimits } from '@/features/usage/types';
import { usePlans, useUsage } from '@/features/usage/hooks';
import { formatCompact, formatNumber } from '@/lib/format';

import { useCreateCheckout, useSubscriptionReport } from './hooks';
import { SUBSCRIPTION_STATUS_LABELS, formatDate, formatPrice } from './types';
import type { PaymentOut } from './types';

const PLAN_LIMIT_FIELDS: { key: keyof PlanLimits; label: string }[] = [
  { key: 'max_websites', label: 'Websites' },
  { key: 'max_monthly_messages', label: 'Messages / mo' },
  { key: 'max_monthly_tokens', label: 'Tokens / mo' },
  { key: 'max_documents', label: 'Documents' },
  { key: 'max_crawl_pages', label: 'Crawl pages / mo' },
];

function formatLimit(value: number | null): string {
  return value === null ? 'Unlimited' : formatNumber(value);
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="font-sans text-lg font-semibold tracking-tight">
      {children}
    </h2>
  );
}

function Header() {
  return (
    <PageHeader
      title="Billing"
      description="Your plan, usage summary, upgrades, and payment history."
    />
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    active: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    trialing: 'bg-sky-500/15 text-sky-600 dark:text-sky-400',
    cancelled: 'bg-muted text-muted-foreground',
    expired: 'bg-muted text-muted-foreground',
  };
  const classes = palette[status] ?? 'bg-muted text-muted-foreground';
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {SUBSCRIPTION_STATUS_LABELS[status] ?? status}
    </span>
  );
}

function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
      </CardHeader>
      <CardContent className="space-y-4">
        {Array.from({ length: rows }, (_, index) => (
          <Skeleton key={index} className="h-4 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

function LimitList({ limits }: { limits: PlanLimits | undefined }) {
  if (!limits) {
    return null;
  }
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-5">
      {PLAN_LIMIT_FIELDS.map(({ key, label }) => (
        <div key={key}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-sm font-medium">{formatLimit(limits[key])}</dd>
        </div>
      ))}
    </dl>
  );
}

function CurrentPlanCard({
  planName,
  planDescription,
  status,
  startDate,
  endDate,
  provider,
  limits,
}: {
  planName: string;
  planDescription: string;
  status: string | null;
  startDate: string | null;
  endDate: string | null;
  provider: string | null;
  limits: PlanLimits | undefined;
}) {
  return (
    <Card className="border-blue-600/40">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <p className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 dark:text-blue-400">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            Current plan
          </p>
          <CardTitle className="font-sans text-3xl font-bold tracking-tight">{planName}</CardTitle>
          <CardDescription>{planDescription}</CardDescription>
        </div>
        {status ? <StatusBadge status={status} /> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {startDate ? (
          <p className="text-sm text-muted-foreground">
            Started {formatDate(startDate)}
            {endDate ? ` · renews ${formatDate(endDate)}` : ''}
          </p>
        ) : null}
        <LimitList limits={limits} />
        {provider ? (
          <p className="text-xs text-muted-foreground capitalize">Paid via {provider}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PlanLimitsList({ limits }: { limits: PlanLimits }) {
  return (
    <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
      {PLAN_LIMIT_FIELDS.map(({ key, label }) => (
        <li key={key} className="flex items-center justify-between gap-2">
          <span>{label}</span>
          <span className="font-medium text-foreground">{formatLimit(limits[key])}</span>
        </li>
      ))}
    </ul>
  );
}

function AvailablePlans({
  currentPlanId,
  onUpgrade,
  pendingPlan,
  error,
}: {
  currentPlanId: string | null;
  onUpgrade: (planId: string) => void;
  pendingPlan: string | null;
  error: string | null;
}) {
  const { data: plans, isPending, isError, error: plansError, refetch } = usePlans();

  if (isPending) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <Card key={index}>
            <CardHeader>
              <Skeleton className="h-5 w-24" />
            </CardHeader>
            <CardContent className="space-y-3">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-9 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorState
        message={plansError?.message ?? 'Failed to load plans.'}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(plans ?? []).map((plan) => {
          const isCurrent = plan.id === currentPlanId;
          const isPurchasable = (plan.price_cents ?? 0) > 0;
          const price = formatPrice(plan.price_cents ?? null, plan.currency ?? 'USD');
          return (
            <div
              key={plan.id}
              aria-current={isCurrent ? 'true' : undefined}
              className={
                isCurrent
                  ? 'relative flex flex-col gap-3 rounded-lg border border-blue-600 bg-blue-600/5 p-4'
                  : 'flex flex-col gap-3 rounded-lg border p-4'
              }
            >
              {isCurrent ? (
                <span className="absolute -top-2.5 left-4 inline-flex items-center gap-1 rounded-full bg-blue-600 px-2 py-0.5 text-xs font-medium text-white">
                  <CheckCircle2 className="size-3" aria-hidden="true" />
                  Current plan
                </span>
              ) : null}
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-medium">{plan.name}</p>
                <p className="text-sm text-muted-foreground">{price}</p>
              </div>
              <p className="text-xs text-muted-foreground">{plan.description}</p>
              <PlanLimitsList limits={plan.limits} />
              <div className="mt-auto pt-2">
                {isCurrent ? (
                  <Button asChild variant="outline" className="w-full">
                    <Link href="/usage">Manage</Link>
                  </Button>
                ) : isPurchasable ? (
                  <Button
                    className="w-full"
                    disabled={pendingPlan === plan.id}
                    onClick={() => onUpgrade(plan.id)}
                  >
                    {pendingPlan === plan.id ? 'Redirecting…' : 'Upgrade'}
                  </Button>
                ) : (
                  <p className="text-center text-xs text-muted-foreground">
                    {plan.id === 'enterprise' ? 'Contact sales' : 'Trial plan'}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function UsageSummaryCard() {
  const { data: usage, isPending, isError, error, refetch } = useUsage();

  if (isPending) {
    return <CardSkeleton rows={2} />;
  }

  if (isError) {
    return (
      <ErrorState
        message={error?.message ?? 'Failed to load usage.'}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usage this month</CardTitle>
        <CardDescription>
          Consumption against the {usage?.plan?.name ?? 'your'} plan.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm text-muted-foreground">Messages</p>
            <p className="font-sans text-xl font-bold">
              {formatNumber(usage?.usage?.messages_sent ?? 0)}
              {usage?.plan?.limits?.max_monthly_messages === null ? (
                <span className="text-xs font-normal text-muted-foreground"> unlimited</span>
              ) : null}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Tokens</p>
            <p className="font-sans text-xl font-bold">
              {formatCompact(usage?.usage?.tokens_used ?? 0)}
              {usage?.plan?.limits?.max_monthly_tokens === null ? (
                <span className="text-xs font-normal text-muted-foreground"> unlimited</span>
              ) : null}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Websites</p>
            <p className="font-sans text-xl font-bold">
              {formatNumber(usage?.usage?.websites ?? 0)}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Documents</p>
            <p className="font-sans text-xl font-bold">
              {formatNumber(usage?.usage?.documents ?? 0)}
            </p>
          </div>
        </div>
        {usage && usage.limits.length > 0 ? (
          <div className="flex flex-col gap-3">
            {usage.limits.map((metric) => {
              const percent =
                metric.percent === null ? null : Math.min(Math.round(metric.percent), 100);
              const barColor =
                percent === null
                  ? 'bg-muted'
                  : percent >= 90
                    ? 'bg-destructive'
                    : percent >= 75
                      ? 'bg-amber-500'
                      : 'bg-blue-600';
              return (
                <div key={metric.metric} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between text-xs">
                    <span>{USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric}</span>
                    <span className="text-muted-foreground">
                      {metric.limit === null
                        ? 'Unlimited'
                        : `${formatNumber(metric.used)} / ${formatNumber(metric.limit)}`}
                    </span>
                  </div>
                  {percent !== null ? (
                    <div
                      role="progressbar"
                      aria-label={`${USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric} usage`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={percent}
                      className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
                    >
                      <div
                        className={`h-full rounded-full ${barColor}`}
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function BillingHistory({ payments }: { payments: PaymentOut[] }) {
  if (payments.length === 0) {
    return (
      <EmptyState
        icon={Receipt}
        title="No payments yet"
        description="Completed payments will appear here after you upgrade."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <caption className="sr-only">Billing history</caption>
        <thead>
          <tr className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
            <th scope="col" className="px-4 py-2 font-medium">
              Date
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              Plan
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              Status
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              Amount
            </th>
            <th scope="col" className="px-4 py-2 font-medium">
              Provider
            </th>
          </tr>
        </thead>
        <tbody>
          {payments.map((payment) => (
            <tr key={payment.id} className="border-b last:border-0">
              <td className="px-4 py-2 text-muted-foreground">{formatDate(payment.created_at)}</td>
              <td className="px-4 py-2 font-medium">{payment.plan_name}</td>
              <td className="px-4 py-2">
                <StatusBadge status={payment.status} />
              </td>
              <td className="px-4 py-2">{formatPrice(payment.amount_cents, payment.currency)}</td>
              <td className="px-4 py-2 text-muted-foreground capitalize">
                {payment.payment_provider ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BillingPage() {
  const { data: report, isPending, isError, error, refetch } = useSubscriptionReport();
  const { data: usage } = useUsage();
  const createCheckout = useCreateCheckout();
  const [pendingPlan, setPendingPlan] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const status = searchParams.get('status');
    if (status === 'success') {
      toast.success('Payment successful! Your plan has been updated.');
      router.replace('/billing');
    } else if (status === 'cancelled') {
      toast.error('Payment was cancelled.');
      router.replace('/billing');
    }
  }, [searchParams, router]);

  const subscription = report?.subscription ?? null;
  const planName = subscription?.plan_name ?? usage?.plan?.name ?? '—';
  const planDescription = usage?.plan?.description ?? 'Your current subscription tier.';
  const currentPlanId = subscription?.plan_id ?? null;

  const handleUpgrade = (planId: string) => {
    setPendingPlan(planId);
    setCheckoutError(null);
    createCheckout.mutate(
      {
        plan_id: planId,
        success_url: `${window.location.origin}/billing?status=success`,
        cancel_url: `${window.location.origin}/billing?status=cancelled`,
      },
      {
        onError: (mutationError: Error) => {
          setCheckoutError(mutationError.message);
          setPendingPlan(null);
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-8">
      <Header />

      {isPending ? <CardSkeleton /> : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load billing information.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError ? (
        <>
          <section aria-labelledby="current-subscription-heading" className="flex flex-col gap-3">
            <SectionHeading id="current-subscription-heading">Current subscription</SectionHeading>
            <CurrentPlanCard
              planName={planName}
              planDescription={planDescription}
              status={subscription?.status ?? null}
              startDate={subscription?.start_date ?? null}
              endDate={subscription?.end_date ?? null}
              provider={subscription?.payment_provider ?? null}
              limits={usage?.plan?.limits}
            />
          </section>

          <section aria-labelledby="usage-summary-heading" className="flex flex-col gap-3">
            <SectionHeading id="usage-summary-heading">Usage summary</SectionHeading>
            <UsageSummaryCard />
          </section>

          <section aria-labelledby="available-plans-heading" className="flex flex-col gap-3">
            <SectionHeading id="available-plans-heading">Available plans</SectionHeading>
            <AvailablePlans
              currentPlanId={currentPlanId}
              onUpgrade={handleUpgrade}
              pendingPlan={pendingPlan}
              error={checkoutError}
            />
          </section>

          <section aria-labelledby="billing-history-heading" className="flex flex-col gap-3">
            <SectionHeading id="billing-history-heading">Billing history</SectionHeading>
            <BillingHistory payments={report?.payments ?? []} />
          </section>
        </>
      ) : null}
    </div>
  );
}

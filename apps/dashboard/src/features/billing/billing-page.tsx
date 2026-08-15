'use client';

import { Receipt } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { usePlans, useUsage } from '@/features/usage/hooks';

import { useCreateCheckout, useSubscriptionReport } from './hooks';
import { SUBSCRIPTION_STATUS_LABELS, formatDate, formatPrice } from './types';
import type { PaymentOut } from './types';

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined).format(value);
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
    .format(value)
    .toLowerCase();
}

function Header() {
  return (
    <div>
      <h1 className="font-sans text-2xl font-bold tracking-tight">Billing</h1>
      <p className="text-sm text-muted-foreground">
        Your plan, usage summary, upgrades, and payment history.
      </p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    active: 'bg-emerald-500/15 text-emerald-600',
    trialing: 'bg-sky-500/15 text-sky-600',
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

function CurrentPlanCard({
  planName,
  planDescription,
  status,
  startDate,
  endDate,
  provider,
}: {
  planName: string;
  planDescription: string;
  status: string | null;
  startDate: string | null;
  endDate: string | null;
  provider: string | null;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle>Current plan</CardTitle>
          <CardDescription>{planDescription}</CardDescription>
        </div>
        {status ? <StatusBadge status={status} /> : null}
      </CardHeader>
      <CardContent>
        <p className="font-sans text-3xl font-bold tracking-tight">{planName}</p>
        {startDate ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Started {formatDate(startDate)}
            {endDate ? ` · renews ${formatDate(endDate)}` : ''}
          </p>
        ) : null}
        {provider ? (
          <p className="mt-1 text-xs text-muted-foreground capitalize">Paid via {provider}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function UpgradeCard({
  onUpgrade,
  pendingPlan,
  error,
}: {
  onUpgrade: (planId: string) => void;
  pendingPlan: string | null;
  error: string | null;
}) {
  const { data: plans, isPending, isError, error: plansError, refetch } = usePlans();

  if (isPending) {
    return <CardSkeleton />;
  }

  if (isError) {
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
      >
        <p className="text-sm text-destructive">{plansError?.message ?? 'Failed to load plans.'}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upgrade</CardTitle>
        <CardDescription>Choose a plan to scale your usage.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        {(plans ?? []).map((plan) => {
          const isPurchasable = (plan.price_cents ?? 0) > 0;
          const price = formatPrice(plan.price_cents ?? null, plan.currency ?? 'USD');
          return (
            <div key={plan.id} className="flex flex-col gap-3 rounded-lg border p-4">
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-medium">{plan.name}</p>
                <p className="text-sm text-muted-foreground">{price}</p>
              </div>
              <p className="text-xs text-muted-foreground">{plan.description}</p>
              <div className="mt-auto">
                {isPurchasable ? (
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
      </CardContent>
      {error ? (
        <CardContent>
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        </CardContent>
      ) : null}
    </Card>
  );
}

function UsageSummaryCard() {
  const { data: usage, isPending, isError, error, refetch } = useUsage();

  if (isPending) {
    return <CardSkeleton rows={2} />;
  }

  if (isError) {
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
      >
        <p className="text-sm text-destructive">{error?.message ?? 'Failed to load usage.'}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usage this month</CardTitle>
        <CardDescription>Consumption against the {usage?.plan.name} plan.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="text-sm text-muted-foreground">Messages</p>
          <p className="font-sans text-xl font-bold">
            {formatNumber(usage?.usage.messages_sent ?? 0)}
            {usage?.plan.limits.max_monthly_messages === null ? (
              <span className="text-xs font-normal text-muted-foreground"> unlimited</span>
            ) : null}
          </p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Tokens</p>
          <p className="font-sans text-xl font-bold">
            {formatCompact(usage?.usage.tokens_used ?? 0)}
            {usage?.plan.limits.max_monthly_tokens === null ? (
              <span className="text-xs font-normal text-muted-foreground"> unlimited</span>
            ) : null}
          </p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Websites</p>
          <p className="font-sans text-xl font-bold">{formatNumber(usage?.usage.websites ?? 0)}</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Documents</p>
          <p className="font-sans text-xl font-bold">{formatNumber(usage?.usage.documents ?? 0)}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function PaymentHistory({ payments }: { payments: PaymentOut[] }) {
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
        <thead>
          <tr className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
            <th className="px-4 py-2 font-medium">Date</th>
            <th className="px-4 py-2 font-medium">Plan</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Amount</th>
            <th className="px-4 py-2 font-medium">Provider</th>
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

  const subscription = report?.subscription ?? null;
  const planName = subscription?.plan_name ?? usage?.plan.name ?? '—';
  const planDescription = usage?.plan.description ?? 'Your current subscription tier.';

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
    <div className="flex flex-col gap-6">
      <Header />

      {isPending ? <CardSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load billing information.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError ? (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <CurrentPlanCard
              planName={planName}
              planDescription={planDescription}
              status={subscription?.status ?? null}
              startDate={subscription?.start_date ?? null}
              endDate={subscription?.end_date ?? null}
              provider={subscription?.payment_provider ?? null}
            />
            <div className="lg:col-span-2">
              <UsageSummaryCard />
            </div>
          </div>

          <UpgradeCard onUpgrade={handleUpgrade} pendingPlan={pendingPlan} error={checkoutError} />

          <Card>
            <CardHeader>
              <CardTitle>Payment history</CardTitle>
              <CardDescription>Every completed billing period.</CardDescription>
            </CardHeader>
            <CardContent>
              <PaymentHistory payments={report?.payments ?? []} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

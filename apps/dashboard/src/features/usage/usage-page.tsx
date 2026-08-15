'use client';

import { CreditCard, FileText, Gauge, MessagesSquare } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { useUsage } from './hooks';
import { USAGE_LIMIT_LABELS } from './types';
import type { UsageMetric } from './types';

const WARNING_THRESHOLD = 80;

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
      <h1 className="font-sans text-2xl font-bold tracking-tight">Usage & Billing</h1>
      <p className="text-sm text-muted-foreground">
        Your plan, limits, and consumption this month.
      </p>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof MessagesSquare;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardDescription>{label}</CardDescription>
        <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <p className="font-sans text-3xl font-bold tracking-tight">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function StatGridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-4 w-24" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-8 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function LimitBar({ metric }: { metric: UsageMetric }) {
  if (metric.limit === null) {
    return (
      <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-medium">
            {USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric}
          </p>
          <p className="text-xs text-muted-foreground">Unlimited</p>
        </div>
      </div>
    );
  }
  const percent = metric.percent ?? 0;
  const width = Math.min(100, percent);
  const nearLimit = percent >= WARNING_THRESHOLD;
  const barColor = nearLimit ? 'bg-amber-500' : 'bg-primary';
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric}</p>
        <p className="text-xs text-muted-foreground">
          {formatNumber(metric.used)} / {formatNumber(metric.limit)}
          {nearLimit ? ' · near limit' : ''}
        </p>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(width)}
        aria-label={`${USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric} usage`}
      >
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export function UsagePage() {
  const { data: usage, isPending, isError, error, refetch } = useUsage();

  return (
    <div className="flex flex-col gap-6">
      <Header />

      {isPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">{error?.message ?? 'Failed to load usage.'}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && usage ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Messages used"
              value={formatNumber(usage.usage.messages_sent)}
              hint={
                usage.plan.limits.max_monthly_messages === null
                  ? 'Unlimited this month'
                  : `Of ${formatNumber(usage.plan.limits.max_monthly_messages)} this month`
              }
              icon={MessagesSquare}
            />
            <StatCard
              label="Tokens used"
              value={formatCompact(usage.usage.tokens_used)}
              hint={
                usage.plan.limits.max_monthly_tokens === null
                  ? 'Unlimited this month'
                  : `Of ${formatCompact(usage.plan.limits.max_monthly_tokens)} this month`
              }
              icon={Gauge}
            />
            <StatCard
              label="Documents"
              value={formatNumber(usage.usage.documents)}
              hint={
                usage.plan.limits.max_documents === null
                  ? 'Unlimited'
                  : `Of ${formatNumber(usage.plan.limits.max_documents)} indexed`
              }
              icon={FileText}
            />
            <StatCard
              label="Current plan"
              value={usage.plan.name}
              hint={usage.plan.description}
              icon={CreditCard}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Monthly limits</CardTitle>
              <CardDescription>
                Consumption against the {usage.plan.name} plan this calendar month.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-6 sm:grid-cols-2">
              {usage.limits.map((metric) => (
                <LimitBar key={metric.metric} metric={metric} />
              ))}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

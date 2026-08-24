'use client';

import { useEffect, useMemo, useState } from 'react';
import nextDynamic from 'next/dynamic';
import { Banknote, CalendarRange, Receipt, TrendingUp } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';

import { formatCents, formatDateTime, formatNumber } from './format';
import { useAdminRevenue } from './hooks';

/**
 * Chart rendering is code-split into `revenue-chart.tsx` so recharts stays
 * out of the main revenue panel bundle. Loads client-side only with a
 * matching skeleton placeholder.
 */
const RevenueChart = nextDynamic(() => import('./revenue-chart').then((mod) => mod.RevenueChart), {
  ssr: false,
  loading: () => (
    <div className="flex h-72 items-center justify-center" role="status" aria-label="Loading chart">
      <Skeleton className="h-4 w-40" />
    </div>
  ),
});

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof Banknote;
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

/** Revenue report (Phase 15 `/api/admin/revenue`). */
export function RevenuePanel() {
  const { data, isPending, isError, error, refetch } = useAdminRevenue();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const chartData = useMemo(() => {
    const periods = data?.periods ?? [];
    return [...periods].reverse().map((period) => ({
      period: period.period,
      revenue: period.revenue_cents,
      payments: period.payments,
    }));
  }, [data]);

  const recentPayments = data?.recent_payments ?? [];

  return (
    <div className="flex flex-col gap-6">
      {isPending ? (
        <div
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          role="status"
          aria-label="Loading revenue"
        >
          {[0, 1, 2, 3].map((index) => (
            <Card key={index}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-24" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">{error?.message ?? 'Failed to load revenue.'}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Total revenue"
              value={formatCents(data.total_revenue_cents, data.currency)}
              hint="Collected across paid billing periods"
              icon={Banknote}
            />
            <StatCard
              label="Paid payments"
              value={formatNumber(data.paid_payments)}
              hint="Successful subscriptions"
              icon={Receipt}
            />
            <StatCard
              label="Active subscriptions"
              value={formatNumber(data.active_subscriptions)}
              hint="Live billing periods"
              icon={TrendingUp}
            />
            <StatCard
              label="Billing months"
              value={formatNumber(data.periods.length)}
              hint={data.periods.length === 1 ? '1 month' : `${data.periods.length} months`}
              icon={CalendarRange}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Revenue by month</CardTitle>
              <CardDescription>Collected amount per calendar month.</CardDescription>
            </CardHeader>
            <CardContent>
              {chartData.length === 0 ? (
                <EmptyState
                  icon={Banknote}
                  title="No revenue yet"
                  description="Paid subscriptions will appear here."
                />
              ) : mounted ? (
                <RevenueChart data={chartData} currency={data.currency} />
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent payments</CardTitle>
              <CardDescription>Newest paid billing periods first.</CardDescription>
            </CardHeader>
            <CardContent>
              {recentPayments.length === 0 ? (
                <EmptyState
                  icon={Receipt}
                  title="No payments yet"
                  description="Checkout completions will be listed here."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Tenant
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Plan
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Amount
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Provider
                        </th>
                        <th scope="col" className="py-2 pr-4 font-medium">
                          Payment ID
                        </th>
                        <th scope="col" className="py-2 font-medium">
                          Date
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentPayments.map((payment) => (
                        <tr key={payment.id} className="border-b">
                          <td className="py-3 pr-4 font-mono text-xs">{payment.tenant_id}</td>
                          <td className="py-3 pr-4 capitalize">{payment.plan_id}</td>
                          <td className="py-3 pr-4 font-medium">
                            {formatCents(payment.amount_cents, payment.currency ?? data.currency)}
                          </td>
                          <td className="py-3 pr-4">{payment.payment_provider ?? '—'}</td>
                          <td className="py-3 pr-4 font-mono text-xs">
                            {payment.payment_id ?? '—'}
                          </td>
                          <td className="py-3 text-muted-foreground">
                            {formatDateTime(payment.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

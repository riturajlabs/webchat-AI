'use client';

/**
 * Chart rendering for the admin revenue report, split into its own module so
 * recharts is code-split out of the revenue panel bundle. Loaded from
 * `revenue-panel.tsx` via `next/dynamic` (`ssr: false`) with a skeleton
 * loading state. Rendering is identical to the previously inlined chart.
 */

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { formatCents } from './format';

function AxisLabelStyle() {
  return { fill: 'var(--muted-foreground)', fontSize: 12 } as const;
}

export function RevenueChart({
  data,
  currency,
}: {
  data: { period: string; revenue: number; payments: number }[];
  currency: string;
}) {
  return (
    <div className="h-72 w-full" data-testid="revenue-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="period" tick={AxisLabelStyle()} tickLine={false} axisLine={false} />
          <YAxis
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatCents(Number(value), currency)}
          />
          <Tooltip
            formatter={(value, name) => [formatCents(Number(value), currency), String(name)]}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Bar dataKey="revenue" name="Revenue" fill="#10b981" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

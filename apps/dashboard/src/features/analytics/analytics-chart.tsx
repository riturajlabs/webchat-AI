'use client';

/**
 * Chart rendering for the analytics page, split into its own module so
 * recharts is code-split out of the main analytics bundle. Loaded from
 * `analytics-page.tsx` via `next/dynamic` (`ssr: false`) with a skeleton
 * loading state. Rendering is identical to the previously inlined charts.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Skeleton } from '@/components/ui/skeleton';

import { formatCompact, formatDay, formatNumber } from './format';
import type { QuestionCount } from './types';

const SERIES_COLORS = {
  conversations: '#6366f1',
  messages: '#10b981',
  inputTokens: '#f59e0b',
  outputTokens: '#8b5cf6',
  questions: '#ec4899',
};

function AxisLabelStyle() {
  return { fill: 'var(--muted-foreground)', fontSize: 12 } as const;
}

export function ChartPlaceholder({ height = 300 }: { height?: number }) {
  return (
    <div
      className="flex items-center justify-center"
      style={{ height }}
      role="status"
      aria-label="Loading chart"
    >
      <Skeleton className="h-4 w-40" />
    </div>
  );
}

export function ActivityChart({
  data,
  mounted,
}: {
  data: { date: string; messages: number; conversations: number }[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder />;
  }
  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label="Bar and line chart of daily messages and conversations"
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
          />
          <YAxis tick={AxisLabelStyle()} tickLine={false} axisLine={false} />
          <Tooltip
            labelFormatter={(label) => formatDay(String(label))}
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Bar
            dataKey="messages"
            name="Messages"
            fill={SERIES_COLORS.messages}
            radius={[4, 4, 0, 0]}
          />
          <Line
            type="monotone"
            dataKey="conversations"
            name="Conversations"
            stroke={SERIES_COLORS.conversations}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TokenChart({
  data,
  mounted,
}: {
  data: { date: string; input_tokens: number; output_tokens: number }[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder />;
  }
  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label="Stacked area chart of daily input and output tokens"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatCompact(Number(value))}
          />
          <Tooltip
            labelFormatter={(label) => formatDay(String(label))}
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Area
            type="monotone"
            dataKey="input_tokens"
            name="Input tokens"
            stackId="tokens"
            stroke={SERIES_COLORS.inputTokens}
            fill={SERIES_COLORS.inputTokens}
            fillOpacity={0.85}
          />
          <Area
            type="monotone"
            dataKey="output_tokens"
            name="Output tokens"
            stackId="tokens"
            stroke={SERIES_COLORS.outputTokens}
            fill={SERIES_COLORS.outputTokens}
            fillOpacity={0.85}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TopWebsitesChart({
  data,
  mounted,
}: {
  data: { website_name: string; conversations: number }[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={320} />;
  }
  const sorted = [...data]
    .sort((a, b) => b.conversations - a.conversations)
    .slice(0, 6)
    .reverse();
  return (
    <div
      className="h-80 w-full"
      role="img"
      aria-label="Horizontal bar chart of conversations per website"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={sorted}
          layout="vertical"
          margin={{ top: 4, right: 8, left: 8, bottom: 0 }}
          data-testid="top-websites-chart"
        >
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tick={AxisLabelStyle()} tickLine={false} axisLine={false} />
          <YAxis
            type="category"
            dataKey="website_name"
            width={110}
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Bar
            dataKey="conversations"
            name="Conversations"
            fill={SERIES_COLORS.conversations}
            radius={[0, 4, 4, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Most-asked questions (Phase 12.5, /api/analytics/questions).
 * Horizontal bars so long question text stays readable; labels truncate to a
 * fixed width via the tick formatter.
 */
export function PopularQuestionsChart({
  data,
  mounted,
}: {
  data: QuestionCount[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={320} />;
  }
  const sorted = [...data]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
    .reverse();
  return (
    <div
      className="h-80 w-full"
      role="img"
      aria-label="Horizontal bar chart of most-asked questions"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={sorted}
          layout="vertical"
          margin={{ top: 4, right: 8, left: 8, bottom: 0 }}
          data-testid="popular-questions-chart"
        >
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="question"
            width={190}
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => {
              const text = String(value);
              return text.length > 22 ? `${text.slice(0, 21)}…` : text;
            }}
          />
          <Tooltip
            formatter={(value) => [formatNumber(Number(value)), 'Asks']}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Bar dataKey="count" name="Asks" fill={SERIES_COLORS.questions} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Star-rating distribution chart (Phase 12.4, UI/UX §12).
 * Renders 5 horizontal bars (1★ → 5★). When no ratings exist yet the
 * component stays mounted so the empty state is legible.
 */
export function FeedbackDistributionChart({
  data,
  mounted,
}: {
  data: { stars: number; count: number }[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={220} />;
  }
  return (
    <div
      className="h-56 w-full"
      role="img"
      aria-label="Horizontal bar chart of 1 to 5 star ratings"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 8, left: 8, bottom: 0 }}
          data-testid="feedback-distribution-chart"
        >
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="stars"
            width={48}
            tick={AxisLabelStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `${value}★`}
          />
          <Tooltip
            labelFormatter={(label) => `${label}★`}
            formatter={(value) => [formatNumber(Number(value)), 'Ratings']}
            contentStyle={{ borderRadius: 8, border: '1px solid var(--border)' }}
          />
          <Bar dataKey="count" name="Ratings" fill={SERIES_COLORS.messages} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

'use client';

/**
 * Chart rendering for the analytics page, split into its own module so
 * recharts is code-split out of the main analytics bundle. Loaded from
 * `analytics-page.tsx` via `next/dynamic` (`ssr: false`) with a skeleton
 * loading state.
 *
 * Every series color is a CSS variable defined in `app/globals.css`
 * (`--chart-1` … `--chart-6`) so charts adapt to light/dark like the rest of
 * the theme — no hard-coded hex values live here.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Skeleton } from '@/components/ui/skeleton';

import { formatCompact, formatDay, formatDayLong, formatNumber, formatRating } from './format';
import type { FeedbackAnalytics, QuestionCount } from './types';

/** Series palette — see globals.css `--chart-*` documentation. */
const COLORS = {
  conversations: 'var(--chart-1)',
  messages: 'var(--chart-2)',
  inputTokens: 'var(--chart-3)',
  outputTokens: 'var(--chart-4)',
  questions: 'var(--chart-5)',
  ratings: 'var(--chart-6)',
} as const;

/** Latency buckets in the order the backend aggregates them. */
export const HISTOGRAM_BUCKETS = ['<1s', '1-2s', '2-5s', '5-10s', '10s+'] as const;

function TickStyle() {
  return { fill: 'var(--muted-foreground)', fontSize: 11 } as const;
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

/**
 * Usage over time: a rounded area for daily messages plus a line for
 * conversations, both drawn with the theme palette.
 */
export function UsageTrendChart({
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
      className="h-80 w-full"
      role="img"
      aria-label="Area and line chart of daily messages and conversations"
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="usage-messages-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.messages} stopOpacity={0.35} />
              <stop offset="95%" stopColor={COLORS.messages} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
          />
          <YAxis tick={TickStyle()} tickLine={false} axisLine={false} />
          <Tooltip
            labelFormatter={(label) => formatDayLong(String(label))}
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ stroke: 'var(--border)' }}
          />
          <Area
            type="monotone"
            dataKey="messages"
            name="Messages"
            stroke={COLORS.messages}
            strokeWidth={2}
            fill="url(#usage-messages-fill)"
          />
          <Line
            type="monotone"
            dataKey="conversations"
            name="Conversations"
            stroke={COLORS.conversations}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Compact stacked area for daily input/output tokens. */
export function TokenChart({
  data,
  mounted,
}: {
  data: { date: string; input_tokens: number; output_tokens: number }[];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={288} />;
  }
  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label="Stacked area chart of daily input and output tokens"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="token-input-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.inputTokens} stopOpacity={0.5} />
              <stop offset="95%" stopColor={COLORS.inputTokens} stopOpacity={0.05} />
            </linearGradient>
            <linearGradient id="token-output-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.outputTokens} stopOpacity={0.5} />
              <stop offset="95%" stopColor={COLORS.outputTokens} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatCompact(Number(value))}
          />
          <Tooltip
            labelFormatter={(label) => formatDayLong(String(label))}
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ stroke: 'var(--border)' }}
          />
          <Area
            type="monotone"
            dataKey="input_tokens"
            name="Input tokens"
            stackId="tokens"
            stroke={COLORS.inputTokens}
            fill="url(#token-input-fill)"
          />
          <Area
            type="monotone"
            dataKey="output_tokens"
            name="Output tokens"
            stackId="tokens"
            stroke={COLORS.outputTokens}
            fill="url(#token-output-fill)"
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
    return <ChartPlaceholder height={256} />;
  }
  const sorted = [...data]
    .sort((a, b) => b.conversations - a.conversations)
    .slice(0, 6)
    .reverse();
  return (
    <div
      className="h-64 w-full"
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
          <XAxis type="number" tick={TickStyle()} tickLine={false} axisLine={false} />
          <YAxis
            type="category"
            dataKey="website_name"
            width={110}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            formatter={(value) => [formatNumber(Number(value)), 'Conversations']}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ fill: 'var(--muted)' }}
          />
          <Bar
            dataKey="conversations"
            name="Conversations"
            fill={COLORS.conversations}
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
    return <ChartPlaceholder height={288} />;
  }
  const sorted = [...data]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
    .reverse();
  return (
    <div
      className="h-72 w-full"
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
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="question"
            width={190}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => {
              const text = String(value);
              return text.length > 22 ? `${text.slice(0, 21)}…` : text;
            }}
          />
          <Tooltip
            formatter={(value) => [formatNumber(Number(value)), 'Asks']}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ fill: 'var(--muted)' }}
          />
          <Bar dataKey="count" name="Asks" fill={COLORS.questions} radius={[0, 4, 4, 0]} />
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
    return <ChartPlaceholder height={224} />;
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
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="stars"
            width={48}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `${value}★`}
          />
          <Tooltip
            labelFormatter={(label) => `${label}★`}
            formatter={(value) => [formatNumber(Number(value)), 'Ratings']}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ fill: 'var(--muted)' }}
          />
          <Bar dataKey="count" name="Ratings" fill={COLORS.ratings} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Response-time histogram (Phase 11.3 rewrite). One bar per latency bucket
 * (<1s → 10s+), in the backend's aggregation order.
 */
export function ResponseHistogramChart({
  distribution,
  mounted,
}: {
  distribution: Record<string, number>;
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={240} />;
  }
  const data = HISTOGRAM_BUCKETS.map((bucket) => ({
    bucket,
    count: distribution[bucket as string] ?? 0,
  }));
  const total = data.reduce((sum, point) => sum + point.count, 0);
  return (
    <div
      className="h-60 w-full"
      role="img"
      aria-label="Bar chart of response time distribution by latency bucket"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
          data-testid="response-histogram-chart"
        >
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            interval={0}
          />
          <YAxis tick={TickStyle()} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip
            labelFormatter={(label) => `Latency ${String(label)}`}
            formatter={(value) => [
              `${formatNumber(Number(value))} (${formatCompact(total > 0 ? (Number(value) / total) * 100 : 0)}%)`,
              'Responses',
            ]}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ fill: 'var(--muted)' }}
          />
          <Bar dataKey="count" name="Responses" fill={COLORS.messages} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Per-day average rating line (Phase 11.3 rewrite). Rendered only when the
 * trend spans at least two rated days, so a single data point never reads as
 * a "trend". Null averages are skipped (the API never emits them).
 */
export function RatingTrendChart({
  data,
  mounted,
}: {
  data: FeedbackAnalytics['trend'];
  mounted: boolean;
}) {
  if (!mounted) {
    return <ChartPlaceholder height={224} />;
  }
  const points = data.filter((point) => point.ratings > 0);
  return (
    <div
      className="h-56 w-full"
      role="img"
      aria-label="Line chart of average visitor rating per day"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDay}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            domain={[1, 5]}
            ticks={[1, 2, 3, 4, 5]}
            tick={TickStyle()}
            tickLine={false}
            axisLine={false}
            width={32}
          />
          <Tooltip
            labelFormatter={(label) => formatDayLong(String(label))}
            formatter={(value, _name) => [formatRating(Number(value)), 'Avg rating']}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--card)',
              color: 'var(--card-foreground)',
            }}
            cursor={{ stroke: 'var(--border)' }}
          />
          <Line
            type="monotone"
            dataKey="average_rating"
            name="Avg rating"
            stroke={COLORS.ratings}
            strokeWidth={2}
            connectNulls
            dot={{ r: 3, fill: COLORS.ratings, strokeWidth: 0 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

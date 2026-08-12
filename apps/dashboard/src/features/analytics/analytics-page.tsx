'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BarChart3, CircleDollarSign, Gauge, MessagesSquare, Star, Timer } from 'lucide-react';
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

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';

import { useWebsites } from '@/features/websites/hooks';

import {
  RANGE_OPTIONS,
  formatCompact,
  formatCost,
  formatDay,
  formatNumber,
  formatRating,
  formatSeconds,
} from './format';
import {
  useAnalyticsPerformance,
  useAnalyticsSummary,
  useAnalyticsTimeseries,
  useAnalyticsTopWebsites,
  useFeedbackSummary,
} from './hooks';
import type { AnalyticsRange } from './types';

const SERIES_COLORS = {
  conversations: '#6366f1',
  messages: '#10b981',
  inputTokens: '#f59e0b',
  outputTokens: '#8b5cf6',
};

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof Timer;
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
      {[0, 1, 2, 3, 4, 5, 6].map((index) => (
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

function ChartShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function ChartPlaceholder({ height = 300 }: { height?: number }) {
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

function AxisLabelStyle() {
  return { fill: 'var(--muted-foreground)', fontSize: 12 } as const;
}

function ActivityChart({
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
    <div className="h-72 w-full">
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

function TokenChart({
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
    <div className="h-72 w-full">
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

function TopWebsitesChart({
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
    <div className="h-80 w-full">
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
 * Star-rating distribution chart (Phase 12.4, UI/UX §12).
 * Renders 5 horizontal bars (1★ → 5★). When no ratings exist yet the
 * component stays mounted so the empty state is legible.
 */
function FeedbackDistributionChart({
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
    <div className="h-56 w-full">
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

export function AnalyticsPage() {
  const router = useRouter();
  const [days, setDays] = useState<AnalyticsRange>(7);
  const [websiteId, setWebsiteId] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const { data: websitesData } = useWebsites();
  const websites = useMemo(() => websitesData ?? [], [websitesData]);

  const {
    data: summary,
    isPending: summaryPending,
    isError,
    error,
    refetch,
  } = useAnalyticsSummary(days, websiteId);
  const { data: timeseries } = useAnalyticsTimeseries(days, websiteId);
  const { data: topWebsites } = useAnalyticsTopWebsites(days);
  const { data: performance } = useAnalyticsPerformance(days, websiteId);
  const { data: feedback } = useFeedbackSummary(days, websiteId);

  const activityData = useMemo(
    () =>
      (timeseries ?? []).map((point) => ({
        date: point.date,
        messages: point.messages,
        conversations: point.conversations,
      })),
    [timeseries],
  );

  const tokenData = useMemo(
    () =>
      (timeseries ?? []).map((point) => ({
        date: point.date,
        input_tokens: point.input_tokens,
        output_tokens: point.output_tokens,
      })),
    [timeseries],
  );

  const feedbackDistribution = useMemo(
    () =>
      [5, 4, 3, 2, 1].map((stars) => ({
        stars,
        count: feedback?.distribution[String(stars)] ?? 0,
      })),
    [feedback],
  );

  const rangeLabel = RANGE_OPTIONS.find((option) => option.value === days)?.label.toLowerCase();

  if (websites.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <Header />
        <EmptyState
          icon={BarChart3}
          title="No analytics yet"
          description="Connect your first website and start chatting to see usage analytics."
          actionLabel="Add a website"
          onAction={() => router.push('/websites')}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Header />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div role="group" aria-label="Time range" className="flex gap-1">
          {RANGE_OPTIONS.map((option) => (
            <Button
              key={option.value}
              type="button"
              variant={days === option.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setDays(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <div className="sm:w-64">
          <label htmlFor="analytics-website-filter" className="sr-only">
            Filter by website
          </label>
          <select
            id="analytics-website-filter"
            value={websiteId}
            onChange={(event) => setWebsiteId(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">All websites</option>
            {websites.map((website) => (
              <option key={website.id} value={website.id}>
                {website.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {summaryPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load analytics.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!summaryPending && !isError && summary ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Conversations"
              value={formatNumber(summary.total_conversations)}
              hint={`Last ${rangeLabel}`}
              icon={MessagesSquare}
            />
            <StatCard
              label="Messages"
              value={formatNumber(summary.total_messages)}
              hint={`Last ${rangeLabel}`}
              icon={MessagesSquare}
            />
            <StatCard
              label="AI responses"
              value={formatNumber(summary.total_ai_responses)}
              hint="Assistant replies"
              icon={BarChart3}
            />
            <StatCard
              label="Tokens"
              value={formatCompact(summary.total_tokens)}
              hint={`${formatNumber(summary.total_input_tokens)} in / ${formatNumber(
                summary.total_output_tokens,
              )} out`}
              icon={Gauge}
            />
            <StatCard
              label="Estimated cost"
              value={formatCost(summary.estimated_cost)}
              hint="At list prices"
              icon={CircleDollarSign}
            />
            <StatCard
              label="Avg response time"
              value={formatSeconds(summary.avg_response_time)}
              hint="Assistant latency"
              icon={Timer}
            />
            <StatCard
              label="User satisfaction"
              value={formatRating(feedback?.average_rating ?? null)}
              hint={
                feedback && feedback.total > 0
                  ? `${formatNumber(feedback.total)} rating${feedback.total === 1 ? '' : 's'}`
                  : 'No ratings yet'
              }
              icon={Star}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="flex flex-col gap-4 lg:col-span-2">
              <ChartShell
                title="Activity over time"
                description="Messages and conversations per day."
              >
                <ActivityChart data={activityData} mounted={mounted} />
              </ChartShell>
              <ChartShell title="Token usage" description="Input and output tokens per day.">
                <TokenChart data={tokenData} mounted={mounted} />
              </ChartShell>
            </div>
            <div className="flex flex-col gap-4">
              <ChartShell
                title="Top websites"
                description="Most active assistants by conversations."
              >
                <TopWebsitesChart
                  data={(topWebsites ?? []).map((item) => ({
                    website_name: item.website_name,
                    conversations: item.conversations,
                  }))}
                  mounted={mounted}
                />
              </ChartShell>
              <PerformanceCard
                avg={performance?.avg_response_time ?? null}
                fastest={performance?.fastest_response_time ?? null}
                slowest={performance?.slowest_response_time ?? null}
              />
              <ChartShell title="User satisfaction" description="How visitors rated the assistant.">
                {feedback && feedback.total > 0 ? (
                  <FeedbackDistributionChart data={feedbackDistribution} mounted={mounted} />
                ) : (
                  <EmptyState
                    icon={Star}
                    title="Awaiting first rating"
                    description="Once visitors rate answers, the 1-5 star breakdown shows up here."
                  />
                )}
              </ChartShell>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function PerformanceCard({
  avg,
  fastest,
  slowest,
}: {
  avg: number | null;
  fastest: number | null;
  slowest: number | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Response time</CardTitle>
        <CardDescription>Assistant latency across the selected period.</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(avg)}</p>
          <p className="text-xs text-muted-foreground">Average</p>
        </div>
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(fastest)}</p>
          <p className="text-xs text-muted-foreground">Fastest</p>
        </div>
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(slowest)}</p>
          <p className="text-xs text-muted-foreground">Slowest</p>
        </div>
      </CardContent>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-sans text-2xl font-bold tracking-tight">Analytics</h1>
      <p className="text-sm text-muted-foreground">
        Chat, token, and assistant-performance usage statistics.
      </p>
    </div>
  );
}

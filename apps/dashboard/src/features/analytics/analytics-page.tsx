'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  BarChart3,
  CircleDollarSign,
  Gauge,
  MessagesSquare,
  Minus,
  Star,
  Timer,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
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
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';

import { useWebsites } from '@/features/websites/hooks';

import {
  RANGE_OPTIONS,
  formatCompact,
  formatCost,
  formatDay,
  formatNumber,
  formatPercent,
  formatRating,
  formatSeconds,
} from './format';
import {
  useAnalyticsFeedback,
  useAnalyticsOverview,
  useAnalyticsPerformance,
  useAnalyticsQuestions,
  useAnalyticsSummary,
  useAnalyticsTimeseries,
  useAnalyticsTopWebsites,
  useFeedbackSummary,
} from './hooks';
import type { AnalyticsRange, QuestionCount } from './types';

const SERIES_COLORS = {
  conversations: '#6366f1',
  messages: '#10b981',
  inputTokens: '#f59e0b',
  outputTokens: '#8b5cf6',
  questions: '#ec4899',
};

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  emphasis = false,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof Timer;
  /** Primary KPIs render larger values so the page reads top-down. */
  emphasis?: boolean;
  /** Blue accent reserved for primary metrics (design tokens §5). */
  accent?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardDescription>{label}</CardDescription>
        <Icon
          className={accent ? 'size-4 text-blue-600' : 'size-4 text-muted-foreground'}
          aria-hidden="true"
        />
      </CardHeader>
      <CardContent>
        <p
          className={
            emphasis
              ? 'font-sans text-3xl font-bold tabular-nums tracking-tight'
              : 'font-sans text-xl font-semibold tabular-nums tracking-tight'
          }
        >
          {value}
        </p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function StatGridSkeleton() {
  return (
    <div role="status" aria-label="Loading analytics" className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <Card key={index}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-9 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[0, 1, 2, 3, 4].map((index) => (
          <Card key={index}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-6 w-14" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="font-sans text-lg font-semibold tracking-tight">
      {children}
    </h2>
  );
}

/**
 * Card wrapper for every chart: title + description double as the chart's
 * accessible name/description via aria-labelledby/aria-describedby.
 */
function ChartShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <Card aria-labelledby={titleId} aria-describedby={descriptionId}>
      <CardHeader>
        <CardTitle id={titleId}>{title}</CardTitle>
        <CardDescription id={descriptionId}>{description}</CardDescription>
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
function PopularQuestionsChart({ data, mounted }: { data: QuestionCount[]; mounted: boolean }) {
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
  const { data: timeseries, isPending: timeseriesPending } = useAnalyticsTimeseries(
    days,
    websiteId,
  );
  const { data: topWebsites, isPending: topWebsitesPending } = useAnalyticsTopWebsites(days);
  const { data: performance } = useAnalyticsPerformance(days, websiteId);
  const { data: feedback } = useFeedbackSummary(days, websiteId);
  const { data: overview } = useAnalyticsOverview(days, websiteId);
  const { data: questions, isPending: questionsPending } = useAnalyticsQuestions(days, websiteId);
  const { data: feedbackAnalytics, isPending: feedbackPending } = useAnalyticsFeedback(
    days,
    websiteId,
  );

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

  const usageTrend = useMemo(() => {
    const series = timeseries ?? [];
    if (series.length < 2) {
      return null;
    }
    const half = Math.floor(series.length / 2);
    const firstHalf = series.slice(0, half).reduce((sum, point) => sum + point.messages, 0);
    const secondHalf = series.slice(half).reduce((sum, point) => sum + point.messages, 0);
    if (firstHalf === 0) {
      return secondHalf > 0 ? { direction: 'up' as const, label: 'New' } : null;
    }
    const change = Math.round(((secondHalf - firstHalf) / firstHalf) * 100);
    return {
      direction: change >= 0 ? ('up' as const) : ('down' as const),
      label: `${change >= 0 ? '+' : ''}${change}%`,
    };
  }, [timeseries]);

  const hasActivity = activityData.some((point) => point.messages > 0 || point.conversations > 0);
  const hasTokens = tokenData.some((point) => point.input_tokens > 0 || point.output_tokens > 0);
  const hasTopWebsites = (topWebsites ?? []).some((item) => item.conversations > 0);

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
        <ErrorState
          message={error?.message ?? 'Failed to load analytics.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!summaryPending && !isError && summary ? (
        <>
          <section aria-labelledby="kpi-heading" className="flex flex-col gap-4">
            <SectionHeading id="kpi-heading">Key metrics</SectionHeading>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Conversations"
                value={formatNumber(summary.total_conversations)}
                hint={`Last ${rangeLabel}`}
                icon={MessagesSquare}
                emphasis
                accent
              />
              <StatCard
                label="Messages"
                value={formatNumber(summary.total_messages)}
                hint={`Last ${rangeLabel}`}
                icon={BarChart3}
                emphasis
                accent
              />
              <StatCard
                label="Resolution Rate"
                value={formatPercent(overview?.resolution_rate ?? 0)}
                hint={
                  overview
                    ? `${formatNumber(overview.successful_answers)} of ${formatNumber(
                        overview.total_ai_responses,
                      )} answers resolved`
                    : 'Assistant answers'
                }
                icon={Gauge}
                emphasis
                accent
              />
              <StatCard
                label="Usage trend"
                value={usageTrend ? usageTrend.label : '—'}
                hint={
                  usageTrend
                    ? 'Messages vs earlier in the period'
                    : 'Not enough data for a trend yet'
                }
                icon={
                  usageTrend ? (usageTrend.direction === 'up' ? TrendingUp : TrendingDown) : Minus
                }
                emphasis
                accent
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <StatCard
                label="Avg response time"
                value={formatSeconds(overview?.avg_response_time ?? summary.avg_response_time)}
                hint="Assistant latency"
                icon={Timer}
              />
              <StatCard
                label="Fallback rate"
                value={formatPercent(overview?.fallback_percentage ?? 0)}
                hint={
                  overview
                    ? `${formatNumber(overview.fallback_responses)} unanswered ${
                        overview.fallback_responses === 1 ? 'question' : 'questions'
                      }`
                    : 'No-context answers'
                }
                icon={Gauge}
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
          </section>

          <section aria-labelledby="engagement-heading" className="flex flex-col gap-3">
            <SectionHeading id="engagement-heading">Activity &amp; engagement</SectionHeading>
            <p className="text-sm text-muted-foreground">
              How visitors find your assistants and what they ask.
            </p>
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="flex flex-col gap-4 lg:col-span-2">
                <ChartShell
                  title="Activity over time"
                  description="Messages and conversations per day."
                >
                  {timeseriesPending ? (
                    <ChartPlaceholder />
                  ) : hasActivity ? (
                    <ActivityChart data={activityData} mounted={mounted} />
                  ) : (
                    <EmptyState
                      icon={MessagesSquare}
                      title="No conversations yet"
                      description="Install your widget on your website to start collecting chats."
                      actionLabel="Set up widget"
                      onAction={() => router.push('/widget')}
                    />
                  )}
                </ChartShell>
                <ChartShell
                  title="Popular questions"
                  description="Most-asked questions in the selected period."
                >
                  {questionsPending ? (
                    <ChartPlaceholder height={320} />
                  ) : questions && questions.length > 0 ? (
                    <PopularQuestionsChart data={questions} mounted={mounted} />
                  ) : (
                    <EmptyState
                      icon={BarChart3}
                      title="No questions yet"
                      description="Once visitors ask the assistant, the most common questions show up here."
                    />
                  )}
                </ChartShell>
                <ChartShell title="Token usage" description="Input and output tokens per day.">
                  {timeseriesPending ? (
                    <ChartPlaceholder />
                  ) : hasTokens ? (
                    <TokenChart data={tokenData} mounted={mounted} />
                  ) : (
                    <EmptyState
                      icon={Gauge}
                      title="No token usage yet"
                      description="Token consumption appears once your assistant starts answering questions."
                    />
                  )}
                </ChartShell>
              </div>
              <div className="flex flex-col gap-4">
                <ChartShell
                  title="Top websites"
                  description="Most active assistants by conversations."
                >
                  {topWebsitesPending ? (
                    <ChartPlaceholder height={320} />
                  ) : hasTopWebsites ? (
                    <TopWebsitesChart
                      data={(topWebsites ?? []).map((item) => ({
                        website_name: item.website_name,
                        conversations: item.conversations,
                      }))}
                      mounted={mounted}
                    />
                  ) : (
                    <EmptyState
                      icon={MessagesSquare}
                      title="No conversations yet"
                      description="Once visitors chat with your assistants, the most active websites appear here."
                    />
                  )}
                </ChartShell>
              </div>
            </div>
          </section>

          <section aria-labelledby="quality-heading" className="flex flex-col gap-3">
            <SectionHeading id="quality-heading">Quality &amp; performance</SectionHeading>
            <p className="text-sm text-muted-foreground">
              Answer quality, latency, and how visitors rate responses.
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <PerformanceCard
                avg={performance?.avg_response_time ?? null}
                fastest={performance?.fastest_response_time ?? null}
                slowest={performance?.slowest_response_time ?? null}
              />
              <ChartShell title="User satisfaction" description="How visitors rated the assistant.">
                {feedbackPending ? (
                  <ChartPlaceholder height={220} />
                ) : feedbackAnalytics && feedbackAnalytics.total > 0 ? (
                  <div className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="rounded-lg border border-border bg-muted/30 p-3">
                        <p className="font-sans text-lg font-bold tracking-tight text-emerald-600">
                          {formatPercent(feedbackAnalytics.positive_percentage)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Positive ({formatNumber(feedbackAnalytics.positive)})
                        </p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/30 p-3">
                        <p className="font-sans text-lg font-bold tracking-tight text-rose-600">
                          {formatPercent(feedbackAnalytics.negative_percentage)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Negative ({formatNumber(feedbackAnalytics.negative)})
                        </p>
                      </div>
                    </div>
                    <FeedbackDistributionChart data={feedbackDistribution} mounted={mounted} />
                  </div>
                ) : (
                  <EmptyState
                    icon={Star}
                    title="Awaiting first rating"
                    description="Once visitors rate answers, the 1-5 star breakdown shows up here."
                  />
                )}
              </ChartShell>
            </div>
          </section>
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
    <PageHeader
      title="Analytics overview"
      description="Chat, token, and assistant-performance usage statistics."
    />
  );
}

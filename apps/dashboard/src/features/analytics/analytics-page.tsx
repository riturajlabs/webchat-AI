'use client';

import dynamic from 'next/dynamic';

import { useEffect, useId, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  BarChart3,
  CircleDollarSign,
  Gauge,
  MessagesSquare,
  Minus,
  RefreshCw,
  Star,
  Timer,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

import { useWebsites } from '@/features/websites/hooks';

import {
  RANGE_OPTIONS,
  changePercent,
  formatChange,
  formatCompact,
  formatCost,
  formatDayLong,
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
import { isValidRange } from './types';
import type {
  AnalyticsDateRange,
  FeedbackAnalytics,
  FeedbackSummary,
  ResponseMetrics,
} from './types';

const UsageTrendChart = dynamic(() => import('./analytics-chart').then((m) => m.UsageTrendChart), {
  ssr: false,
  loading: () => <ChartPlaceholder />,
});

const TokenChart = dynamic(() => import('./analytics-chart').then((m) => m.TokenChart), {
  ssr: false,
  loading: () => <ChartPlaceholder height={288} />,
});

const TopWebsitesChart = dynamic(
  () => import('./analytics-chart').then((m) => m.TopWebsitesChart),
  { ssr: false, loading: () => <ChartPlaceholder height={256} /> },
);

const PopularQuestionsChart = dynamic(
  () => import('./analytics-chart').then((m) => m.PopularQuestionsChart),
  { ssr: false, loading: () => <ChartPlaceholder height={288} /> },
);

const FeedbackDistributionChart = dynamic(
  () => import('./analytics-chart').then((m) => m.FeedbackDistributionChart),
  { ssr: false, loading: () => <ChartPlaceholder height={224} /> },
);

const ResponseHistogramChart = dynamic(
  () => import('./analytics-chart').then((m) => m.ResponseHistogramChart),
  { ssr: false, loading: () => <ChartPlaceholder height={240} /> },
);

const RatingTrendChart = dynamic(
  () => import('./analytics-chart').then((m) => m.RatingTrendChart),
  { ssr: false, loading: () => <ChartPlaceholder height={224} /> },
);

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="font-sans text-lg font-semibold tracking-tight">
      {children}
    </h2>
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

function DeltaChip({
  change,
  invert = false,
  note,
}: {
  change: number | null;
  invert?: boolean;
  note?: string;
}) {
  if (change === null || !Number.isFinite(change)) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Minus className="size-3.5" aria-hidden="true" />
        New
      </span>
    );
  }
  const improved = invert ? change < 0 : change > 0;
  const flat = change === 0;
  const Icon = flat ? Minus : improved ? TrendingUp : TrendingDown;
  const className = cn(
    'inline-flex items-center gap-1 text-xs font-medium tabular-nums',
    flat
      ? 'text-muted-foreground'
      : improved
        ? 'text-emerald-600 dark:text-emerald-500'
        : 'text-rose-600 dark:text-rose-500',
  );
  return (
    <span className={className} title={note ?? 'vs the previous period'}>
      <Icon className="size-3.5" aria-hidden="true" />
      {formatChange(change)}
    </span>
  );
}

function StatCard({
  label,
  value,
  delta,
  deltaInvert = false,
  hint,
  icon: Icon,
  emphasis = false,
  accent = false,
}: {
  label: string;
  value: string;
  delta?: number | null;
  deltaInvert?: boolean;
  hint?: string;
  icon: typeof Timer;
  emphasis?: boolean;
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
        {delta !== undefined ? (
          <div className="mt-1.5">
            <DeltaChip change={delta} invert={deltaInvert} />
          </div>
        ) : null}
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
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
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

function InlineLegend({ items }: { items: { label: string; className: string }[] }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
      {items.map((item) => (
        <span
          key={item.label}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
        >
          <span className={cn('size-2 rounded-full', item.className)} aria-hidden="true" />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function PerformanceStat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
      <p className="font-sans text-xl font-bold tabular-nums tracking-tight">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
      {hint ? <p className="text-[11px] text-muted-foreground/70">{hint}</p> : null}
    </div>
  );
}

function PerformanceCard({
  performance,
  pending,
  hasData,
  mounted,
}: {
  performance: ResponseMetrics | undefined;
  pending: boolean;
  hasData: boolean;
  mounted: boolean;
}) {
  return (
    <Card aria-labelledby="performance-title" aria-describedby="performance-description">
      <CardHeader>
        <CardTitle id="performance-title">Response time</CardTitle>
        <CardDescription id="performance-description">
          Assistant latency across the selected period.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {pending && !performance ? (
          <ChartPlaceholder height={300} />
        ) : !hasData ? (
          <EmptyState
            icon={Timer}
            title="No response time data yet"
            description="Latency statistics appear once your assistant starts answering questions."
          />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-3 gap-4">
              <PerformanceStat
                label="Average"
                value={formatSeconds(performance?.avg_response_time ?? null)}
              />
              <PerformanceStat
                label="Median"
                value={formatSeconds(performance?.median_response_time ?? null)}
              />
              <PerformanceStat
                label="P95"
                value={formatSeconds(performance?.p95_response_time ?? null)}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Fastest {formatSeconds(performance?.fastest_response_time ?? null)}</span>
              <span>Slowest {formatSeconds(performance?.slowest_response_time ?? null)}</span>
            </div>
            <ResponseHistogramChart
              distribution={performance?.distribution ?? {}}
              mounted={mounted}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SatisfactionCard({
  feedbackAnalytics,
  feedback,
  pending,
  hasRatings,
  mounted,
}: {
  feedbackAnalytics: FeedbackAnalytics | undefined;
  feedback: FeedbackSummary | undefined;
  pending: boolean;
  hasRatings: boolean;
  mounted: boolean;
}) {
  const average = feedbackAnalytics?.average_rating ?? feedback?.average_rating ?? null;
  const total = feedbackAnalytics?.total ?? feedback?.total ?? 0;
  return (
    <Card aria-labelledby="satisfaction-title" aria-describedby="satisfaction-description">
      <CardHeader>
        <CardTitle id="satisfaction-title">User satisfaction</CardTitle>
        <CardDescription id="satisfaction-description">
          How visitors rated the assistant.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {pending && !feedbackAnalytics ? (
          <ChartPlaceholder height={300} />
        ) : !hasRatings ? (
          <EmptyState
            icon={Star}
            title="Awaiting first rating"
            description="Once visitors rate answers, the 1-5 star breakdown shows up here."
          />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="font-sans text-3xl font-bold tabular-nums tracking-tight">
                  {formatRating(average)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatNumber(total)} rating{total === 1 ? '' : 's'} in the selected period
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-border bg-muted/30 p-3">
                  <p className="font-sans text-lg font-bold tracking-tight text-emerald-600 dark:text-emerald-500">
                    {formatPercent(feedbackAnalytics?.positive_percentage ?? 0)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Positive ({formatNumber(feedbackAnalytics?.positive ?? 0)})
                  </p>
                </div>
                <div className="rounded-lg border border-border bg-muted/30 p-3">
                  <p className="font-sans text-lg font-bold tracking-tight text-rose-600 dark:text-rose-500">
                    {formatPercent(feedbackAnalytics?.negative_percentage ?? 0)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Negative ({formatNumber(feedbackAnalytics?.negative ?? 0)})
                  </p>
                </div>
              </div>
            </div>
            <FeedbackDistributionChart
              data={[5, 4, 3, 2, 1].map((stars) => ({
                stars,
                count: feedbackAnalytics?.distribution[String(stars)] ?? 0,
              }))}
              mounted={mounted}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function InsightsGrid({
  insights,
}: {
  insights: { label: string; detail: string; icon: typeof Timer }[];
}) {
  if (insights.length === 0) {
    return (
      <EmptyState
        icon={BarChart3}
        title="Not enough data for insights yet"
        description="Once visitors chat with your assistants, this section will highlight the trends worth knowing."
      />
    );
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {insights.map((insight) => (
        <div key={insight.label} className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <insight.icon className="size-4 text-blue-600" aria-hidden="true" />
            <p className="text-sm font-medium">{insight.label}</p>
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">{insight.detail}</p>
        </div>
      ))}
    </div>
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

function rangeWindowLabel(range: AnalyticsDateRange): string {
  if (range.preset === 'custom') {
    return 'selected period';
  }
  return `${range.preset} days`;
}

export function AnalyticsPage() {
  const router = useRouter();
  const [range, setRange] = useState<AnalyticsDateRange>({ preset: 7 });
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
  } = useAnalyticsSummary(range, websiteId);
  const { data: timeseries, isPending: timeseriesPending } = useAnalyticsTimeseries(
    range,
    websiteId,
  );
  const { data: topWebsites, isPending: topWebsitesPending } = useAnalyticsTopWebsites(range);
  const { data: performance, isPending: performancePending } = useAnalyticsPerformance(
    range,
    websiteId,
  );
  const { data: feedback, isPending: feedbackSummaryPending } = useFeedbackSummary(
    range,
    websiteId,
  );
  const { data: overview } = useAnalyticsOverview(range, websiteId);
  const { data: questions, isPending: questionsPending } = useAnalyticsQuestions(range, websiteId);
  const { data: feedbackAnalytics, isPending: feedbackPending } = useAnalyticsFeedback(
    range,
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

  const hasActivity = activityData.some((point) => point.messages > 0 || point.conversations > 0);
  const hasTokens = tokenData.some((point) => point.input_tokens > 0 || point.output_tokens > 0);
  const hasTopWebsites = (topWebsites ?? []).some((item) => item.conversations > 0);
  const hasQuestions = (questions?.length ?? 0) > 0;

  const hasPerformance = Boolean(
    performance &&
    (performance.avg_response_time != null ||
      performance.median_response_time != null ||
      performance.p95_response_time != null ||
      Object.values(performance.distribution).some((count) => count > 0)),
  );

  const hasRatings = (feedbackAnalytics?.total ?? feedback?.total ?? 0) > 0;

  const ratingTrend = useMemo(
    () => (feedbackAnalytics?.trend ?? []).filter((point) => point.ratings > 0),
    [feedbackAnalytics],
  );

  const insights = useMemo(() => {
    const items: { label: string; detail: string; icon: typeof Timer }[] = [];
    const busy = (timeseries ?? []).reduce<{ date: string; messages: number } | null>(
      (best, point) => (point.messages > (best?.messages ?? 0) ? point : best),
      null,
    );
    if (busy && busy.messages > 0) {
      items.push({
        label: 'Busiest day',
        detail: `${formatDayLong(busy.date)} with ${formatNumber(busy.messages)} messages`,
        icon: TrendingUp,
      });
    }
    if (hasRatings) {
      const distribution = feedbackAnalytics?.distribution ?? {};
      const top = [5, 4, 3, 2, 1].reduce<number | null>((best, stars) => {
        const bestCount = best === null ? -1 : (distribution[String(best)] ?? 0);
        return (distribution[String(stars)] ?? 0) > bestCount ? stars : best;
      }, null);
      if (top !== null && (distribution[String(top)] ?? 0) > 0) {
        items.push({
          label: 'Most common rating',
          detail: `${top}★`,
          icon: Star,
        });
      }
    }
    if (overview && overview.total_ai_responses > 0) {
      items.push({
        label: 'Fallback usage',
        detail:
          overview.fallback_percentage > 0
            ? `${formatPercent(overview.fallback_percentage)} of answers used the no-context fallback`
            : 'No answers fell back to the no-context response',
        icon: Gauge,
      });
    }
    if (summary && summary.avg_response_time != null) {
      const latencyChange = changePercent(
        summary.avg_response_time,
        summary.previous_avg_response_time,
      );
      if (latencyChange !== null && latencyChange !== 0) {
        items.push({
          label: 'Latency trend',
          detail:
            latencyChange < 0
              ? `Average response time improved ${formatChange(latencyChange)} vs the previous period`
              : `Average response time increased ${formatChange(latencyChange)} vs the previous period`,
          icon: Timer,
        });
      }
    }
    return items.slice(0, 4);
  }, [timeseries, hasRatings, feedbackAnalytics, overview, summary]);

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

  const rangeInvalid = !isValidRange(range) && !summaryPending && !isError;

  return (
    <div className="flex flex-col gap-6">
      <Header />

      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-3">
          <div role="group" aria-label="Time range" className="flex gap-1">
            {RANGE_OPTIONS.map((option) => (
              <Button
                key={option.value}
                type="button"
                variant={range.preset === option.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => {
                  setRange((previous) =>
                    option.value === 'custom'
                      ? { preset: 'custom', start: previous.start, end: previous.end }
                      : { preset: option.value },
                  );
                }}
              >
                {option.label}
              </Button>
            ))}
          </div>
          {range.preset === 'custom' ? (
            <div className="flex items-center gap-2">
              <label htmlFor="analytics-start" className="sr-only">
                Start date
              </label>
              <input
                id="analytics-start"
                type="date"
                value={range.start ?? ''}
                onChange={(event) =>
                  setRange({ preset: 'custom', start: event.target.value, end: range.end })
                }
                className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <span aria-hidden="true" className="text-sm text-muted-foreground">
                →
              </span>
              <label htmlFor="analytics-end" className="sr-only">
                End date
              </label>
              <input
                id="analytics-end"
                type="date"
                value={range.end ?? ''}
                onChange={(event) =>
                  setRange({ preset: 'custom', start: range.start, end: event.target.value })
                }
                className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <div className="w-full sm:w-64">
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label="Refresh analytics"
            onClick={() => void refetch()}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {summaryPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load analytics.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {rangeInvalid ? (
        <EmptyState
          icon={Timer}
          title="Pick a date range"
          description="Select a start and end date above to see analytics for that period."
        />
      ) : null}

      {!summaryPending && !isError && summary && !rangeInvalid ? (
        <>
          <section aria-labelledby="kpi-heading" className="flex flex-col gap-4">
            <SectionHeading id="kpi-heading">Key metrics</SectionHeading>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Conversations"
                value={formatNumber(summary.total_conversations)}
                delta={changePercent(summary.total_conversations, summary.previous_conversations)}
                hint={`vs previous ${rangeWindowLabel(range)}`}
                icon={MessagesSquare}
                emphasis
                accent
              />
              <StatCard
                label="Messages"
                value={formatNumber(summary.total_messages)}
                delta={changePercent(summary.total_messages, summary.previous_messages)}
                hint={`vs previous ${rangeWindowLabel(range)}`}
                icon={BarChart3}
                emphasis
                accent
              />
              <StatCard
                label="Tokens"
                value={formatCompact(summary.total_tokens)}
                delta={changePercent(summary.total_tokens, summary.previous_tokens)}
                hint={`vs previous ${rangeWindowLabel(range)}`}
                icon={Gauge}
                emphasis
                accent
              />
              <StatCard
                label="Avg response time"
                value={formatSeconds(
                  summary.avg_response_time ??
                    performance?.avg_response_time ??
                    overview?.avg_response_time ??
                    null,
                )}
                delta={changePercent(
                  summary.avg_response_time ??
                    performance?.avg_response_time ??
                    overview?.avg_response_time ??
                    null,
                  summary.previous_avg_response_time,
                )}
                deltaInvert
                hint="Lower is better"
                icon={Timer}
                emphasis
                accent
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Estimated cost"
                value={formatCost(summary.estimated_cost)}
                hint="At list prices"
                icon={CircleDollarSign}
              />
              <StatCard
                label="Resolution rate"
                value={formatPercent(overview?.resolution_rate ?? 0)}
                hint={
                  overview
                    ? `${formatNumber(overview.successful_answers)} of ${formatNumber(
                        overview.total_ai_responses,
                      )} answers resolved`
                    : 'Assistant answers'
                }
                icon={Gauge}
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
                label="User satisfaction"
                value={formatRating(
                  feedbackAnalytics?.average_rating ?? feedback?.average_rating ?? null,
                )}
                hint={
                  hasRatings
                    ? `${formatNumber(
                        feedbackAnalytics?.total ?? feedback?.total ?? 0,
                      )} rating${(feedbackAnalytics?.total ?? feedback?.total ?? 0) === 1 ? '' : 's'} received`
                    : 'No ratings yet'
                }
                icon={Star}
              />
            </div>
          </section>

          <section aria-labelledby="engage-heading" className="flex flex-col gap-3">
            <SectionHeading id="engage-heading">Usage &amp; engagement</SectionHeading>
            <p className="text-sm text-muted-foreground">
              How visitors find your assistants, chat, and consume tokens.
            </p>
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <ChartShell
                  title="Usage over time"
                  description="Messages and conversations per day (conversations in blue)."
                >
                  {timeseriesPending && !activityData.length ? (
                    <ChartPlaceholder />
                  ) : hasActivity ? (
                    <>
                      <InlineLegend
                        items={[
                          { label: 'Daily messages', className: 'bg-[var(--chart-2)]' },
                          { label: 'Daily conversations', className: 'bg-[var(--chart-1)]' },
                        ]}
                      />
                      <UsageTrendChart data={activityData} mounted={mounted} />
                    </>
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
              </div>
              <ChartShell
                title="Token usage"
                description="Daily token consumption and the period totals."
              >
                {timeseriesPending && !tokenData.length ? (
                  <ChartPlaceholder height={288} />
                ) : hasTokens ? (
                  <>
                    <div className="mb-3 grid grid-cols-3 gap-2">
                      <div className="rounded-lg border border-border bg-muted/30 p-2 text-center">
                        <p className="font-sans text-base font-bold tabular-nums tracking-tight">
                          {formatCompact(summary.total_tokens)}
                        </p>
                        <p className="text-[11px] text-muted-foreground">Total</p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/30 p-2 text-center">
                        <p className="font-sans text-base font-bold tabular-nums tracking-tight">
                          {formatCompact(summary.total_input_tokens)}
                        </p>
                        <p className="text-[11px] text-muted-foreground">Input</p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/30 p-2 text-center">
                        <p className="font-sans text-base font-bold tabular-nums tracking-tight">
                          {formatCompact(summary.total_output_tokens)}
                        </p>
                        <p className="text-[11px] text-muted-foreground">Output</p>
                      </div>
                    </div>
                    <TokenChart data={tokenData} mounted={mounted} />
                  </>
                ) : (
                  <EmptyState
                    icon={Gauge}
                    title="No token usage yet"
                    description="Token consumption appears once your assistant starts answering questions."
                  />
                )}
              </ChartShell>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <ChartShell
                title="Top websites"
                description={
                  websiteId
                    ? 'Most active assistants across all websites.'
                    : 'Most active assistants by conversations.'
                }
              >
                {topWebsitesPending && !hasTopWebsites ? (
                  <ChartPlaceholder height={256} />
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
              <ChartShell
                title="Popular questions"
                description="Most-asked questions in the selected period."
              >
                {questionsPending && !hasQuestions ? (
                  <ChartPlaceholder height={288} />
                ) : hasQuestions ? (
                  <PopularQuestionsChart data={questions ?? []} mounted={mounted} />
                ) : (
                  <EmptyState
                    icon={BarChart3}
                    title="No questions yet"
                    description="Once visitors ask the assistant, the most common questions show up here."
                  />
                )}
              </ChartShell>
            </div>
          </section>

          <section aria-labelledby="quality-heading" className="flex flex-col gap-3">
            <SectionHeading id="quality-heading">Quality &amp; performance</SectionHeading>
            <p className="text-sm text-muted-foreground">
              Answer quality, latency, and how visitors rate responses.
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <PerformanceCard
                performance={performance}
                pending={performancePending}
                hasData={hasPerformance}
                mounted={mounted}
              />
              <SatisfactionCard
                feedbackAnalytics={feedbackAnalytics}
                feedback={feedback}
                pending={feedbackPending || feedbackSummaryPending}
                hasRatings={hasRatings}
                mounted={mounted}
              />
            </div>
            {hasRatings && ratingTrend.length >= 2 ? (
              <ChartShell
                title="Rating over time"
                description="Average visitor rating per day on a 1-5 star scale."
              >
                <RatingTrendChart data={ratingTrend} mounted={mounted} />
              </ChartShell>
            ) : null}
          </section>

          <section aria-labelledby="insights-heading" className="flex flex-col gap-3">
            <SectionHeading id="insights-heading">Quality insights</SectionHeading>
            <p className="text-sm text-muted-foreground">
              Highlights worth knowing, derived from your real data.
            </p>
            <InsightsGrid insights={insights} />
          </section>
        </>
      ) : null}
    </div>
  );
}

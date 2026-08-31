/**
 * React Query hooks for the analytics feature (Phase 11.3 + 12.4,
 * 00-AI-Development-Rules §14). Every hook accepts an `AnalyticsDateRange`
 * (preset day counts or a custom start/end span) plus an optional website
 * filter, so the page can switch windows without refetching by hand.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

import { isValidRange } from './types';
import type {
  AnalyticsDateRange,
  AnalyticsOverview,
  AnalyticsSummary,
  FeedbackAnalytics,
  FeedbackSummary,
  QuestionCount,
  ResponseMetrics,
  TimeseriesPoint,
  TopWebsite,
} from './types';

export const analyticsKeys = {
  all: ['analytics'] as const,
  summary: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'summary', { range, websiteId }] as const,
  timeseries: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'timeseries', { range, websiteId }] as const,
  topWebsites: (range: AnalyticsDateRange) => ['analytics', 'top-websites', { range }] as const,
  performance: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'performance', { range, websiteId }] as const,
  feedback: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'feedback', { range, websiteId }] as const,
  feedbackAnalytics: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'feedback-analytics', { range, websiteId }] as const,
  overview: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'overview', { range, websiteId }] as const,
  questions: (range: AnalyticsDateRange, websiteId: string) =>
    ['analytics', 'questions', { range, websiteId }] as const,
};

export interface AnalyticsFilters {
  range: AnalyticsDateRange;
  websiteId: string;
}

/**
 * `?days=30`, `?start=2026-08-01&end=2026-08-30`, or `''` when the range is
 * not complete yet (the page keeps the previous in-flight data instead).
 */
export function windowQuery(range: AnalyticsDateRange): string {
  if (!isValidRange(range)) {
    return '';
  }
  const params = new URLSearchParams();
  if (range.preset === 'custom') {
    params.set('start', range.start ?? '');
    params.set('end', range.end ?? '');
  } else {
    params.set('days', String(range.preset));
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

function websiteQuery(websiteId: string): string {
  return websiteId ? `&website_id=${encodeURIComponent(websiteId)}` : '';
}

export function useAnalyticsSummary(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.summary(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<AnalyticsSummary>(
        `/api/analytics/summary${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

export function useAnalyticsTimeseries(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.timeseries(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<TimeseriesPoint[]>(
        `/api/analytics/timeseries${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

export function useAnalyticsTopWebsites(range: AnalyticsDateRange) {
  return useQuery({
    queryKey: analyticsKeys.topWebsites(range),
    enabled: isValidRange(range),
    queryFn: () => api.get<TopWebsite[]>(`/api/analytics/top-websites${windowQuery(range)}`),
  });
}

export function useAnalyticsPerformance(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.performance(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<ResponseMetrics>(
        `/api/analytics/performance${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

/**
 * Visitor satisfaction (Phase 12.4, UI/UX §12).
 * Returns the average rating + the 1-5 star distribution for the window.
 */
export function useFeedbackSummary(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.feedback(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<FeedbackSummary>(
        `/api/feedback/summary${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

/**
 * Resolution metrics (Phase 12.5, /api/analytics/overview).
 * Successful answers, fallback rate, resolution rate and response time.
 */
export function useAnalyticsOverview(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.overview(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<AnalyticsOverview>(
        `/api/analytics/overview${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

/**
 * Feedback sentiment (Phase 12.5, /api/analytics/feedback).
 * Positive = ratings 4-5, negative = 1-2, neutral = 3, plus the per-day
 * rating trend for the window.
 */
export function useAnalyticsFeedback(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.feedbackAnalytics(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () =>
      api.get<FeedbackAnalytics>(
        `/api/analytics/feedback${windowQuery(range)}${websiteQuery(websiteId)}`,
      ),
  });
}

/** Most-asked user questions in the window (Phase 12.5). */
export function useAnalyticsQuestions(range: AnalyticsDateRange, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.questions(range, websiteId),
    enabled: isValidRange(range),
    queryFn: () => {
      const params = new URLSearchParams(windowQuery(range).replace(/^\?/, ''));
      params.set('limit', '10');
      return api.get<QuestionCount[]>(
        `/api/analytics/questions?${params.toString()}${websiteQuery(websiteId)}`,
      );
    },
  });
}

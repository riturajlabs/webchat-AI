/**
 * React Query hooks for the analytics feature (Phase 11.3 + 12.4,
 * 00-AI-Development-Rules §14).
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type {
  AnalyticsOverview,
  AnalyticsRange,
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
  summary: (days: number, websiteId: string) =>
    ['analytics', 'summary', { days, websiteId }] as const,
  timeseries: (days: number, websiteId: string) =>
    ['analytics', 'timeseries', { days, websiteId }] as const,
  topWebsites: (days: number) => ['analytics', 'top-websites', { days }] as const,
  performance: (days: number, websiteId: string) =>
    ['analytics', 'performance', { days, websiteId }] as const,
  feedback: (days: number, websiteId: string) =>
    ['analytics', 'feedback', { days, websiteId }] as const,
  overview: (days: number, websiteId: string) =>
    ['analytics', 'overview', { days, websiteId }] as const,
  questions: (days: number, websiteId: string) =>
    ['analytics', 'questions', { days, websiteId }] as const,
};

export interface AnalyticsFilters {
  days: AnalyticsRange;
  websiteId: string;
}

function websiteQuery(websiteId: string): string {
  return websiteId ? `&website_id=${encodeURIComponent(websiteId)}` : '';
}

export function useAnalyticsSummary(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.summary(days, websiteId),
    queryFn: () =>
      api.get<AnalyticsSummary>(`/api/analytics/summary?days=${days}${websiteQuery(websiteId)}`),
  });
}

export function useAnalyticsTimeseries(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.timeseries(days, websiteId),
    queryFn: () =>
      api.get<TimeseriesPoint[]>(
        `/api/analytics/timeseries?days=${days}${websiteQuery(websiteId)}`,
      ),
  });
}

export function useAnalyticsTopWebsites(days: number) {
  return useQuery({
    queryKey: analyticsKeys.topWebsites(days),
    queryFn: () => api.get<TopWebsite[]>(`/api/analytics/top-websites?days=${days}`),
  });
}

export function useAnalyticsPerformance(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.performance(days, websiteId),
    queryFn: () =>
      api.get<ResponseMetrics>(`/api/analytics/performance?days=${days}${websiteQuery(websiteId)}`),
  });
}

/**
 * Visitor satisfaction (Phase 12.4, UI/UX §12).
 * Returns the average rating + the 1-5 star distribution for the window.
 */
export function useFeedbackSummary(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.feedback(days, websiteId),
    queryFn: () =>
      api.get<FeedbackSummary>(`/api/feedback/summary?days=${days}${websiteQuery(websiteId)}`),
  });
}

/**
 * Resolution metrics (Phase 12.5, /api/analytics/overview).
 * Successful answers, fallback rate, resolution rate and response time.
 */
export function useAnalyticsOverview(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.overview(days, websiteId),
    queryFn: () =>
      api.get<AnalyticsOverview>(`/api/analytics/overview?days=${days}${websiteQuery(websiteId)}`),
  });
}

/**
 * Feedback sentiment (Phase 12.5, /api/analytics/feedback).
 * Positive = ratings 4-5, negative = 1-2, neutral = 3.
 */
export function useAnalyticsFeedback(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.feedback(days, websiteId),
    queryFn: () =>
      api.get<FeedbackAnalytics>(`/api/analytics/feedback?days=${days}${websiteQuery(websiteId)}`),
  });
}

/** Most-asked user questions in the window (Phase 12.5). */
export function useAnalyticsQuestions(days: number, websiteId: string) {
  return useQuery({
    queryKey: analyticsKeys.questions(days, websiteId),
    queryFn: () =>
      api.get<QuestionCount[]>(
        `/api/analytics/questions?days=${days}${websiteQuery(websiteId)}&limit=10`,
      ),
  });
}

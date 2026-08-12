/**
 * React Query hooks for the analytics feature (Phase 11.3 + 12.4,
 * 00-AI-Development-Rules §14).
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type {
  AnalyticsRange,
  AnalyticsSummary,
  FeedbackSummary,
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

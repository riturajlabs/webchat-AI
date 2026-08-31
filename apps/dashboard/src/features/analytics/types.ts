/**
 * Analytics domain types mirrored from the backend API (Phase 11.3 + 12.4,
 * redesigned: previous-period, median/p95/distribution, rating trend, custom
 * date range).
 */

export interface AnalyticsSummary {
  total_conversations: number;
  total_messages: number;
  total_ai_responses: number;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  estimated_cost: number;
  avg_response_time: number | null;
  /** The immediately preceding window of equal length (empty/zero when none). */
  previous_conversations: number;
  previous_messages: number;
  previous_tokens: number;
  previous_avg_response_time: number | null;
}

export interface TimeseriesPoint {
  date: string;
  conversations: number;
  messages: number;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
}

export interface TopWebsite {
  website_id: string;
  website_name: string;
  conversations: number;
  messages: number;
}

/**
 * Performance metrics (seconds). `distribution` keys are the latency buckets
 * `<1s`, `1-2s`, `2-5s`, `5-10s`, `10s+`; `median`/`p95` are nearest-rank.
 */
export interface ResponseMetrics {
  avg_response_time: number | null;
  fastest_response_time: number | null;
  slowest_response_time: number | null;
  median_response_time: number | null;
  p95_response_time: number | null;
  distribution: Record<string, number>;
}

/**
 * User-satisfaction breakdown (UI/UX §12, Phase 12.4).
 * `distribution` keys are 1-5 stars (JSON object keys are always strings).
 */
export interface FeedbackSummary {
  total: number;
  average_rating: number | null;
  distribution: Record<string, number>;
}

/**
 * Resolution metrics (Phase 12.5, /api/analytics/overview).
 * Rates are percentages over the window's assistant responses; the fallback
 * text is the no-context answer the RAG pipeline returns.
 */
export interface AnalyticsOverview {
  total_conversations: number;
  total_messages: number;
  total_questions: number;
  total_ai_responses: number;
  successful_answers: number;
  fallback_responses: number;
  resolution_rate: number;
  fallback_percentage: number;
  avg_response_time: number | null;
}

/** One popular user question and how often it was asked (Phase 12.5). */
export interface QuestionCount {
  question: string;
  count: number;
}

/** One day of visitor satisfaction for the rating trend chart. */
export interface RatingTrendPoint {
  date: string;
  average_rating: number | null;
  ratings: number;
}

/**
 * Feedback sentiment (Phase 12.5, /api/analytics/feedback).
 * Positive = ratings 4-5, neutral = 3, negative = 1-2. `trend` is the per-day
 * average rating (oldest-first); the dashboard renders a line only when it
 * spans at least two days.
 */
export interface FeedbackAnalytics {
  total: number;
  positive: number;
  negative: number;
  neutral: number;
  positive_percentage: number;
  negative_percentage: number;
  average_rating: number | null;
  distribution: Record<string, number>;
  trend: RatingTrendPoint[];
}

/** Present (7/30/90 days) or a custom inclusive date span. */
export type DatePreset = 7 | 30 | 90 | 'custom';

export type AnalyticsRange = Exclude<DatePreset, 'custom'>;

/** Selected analytics window shared by every hook. */
export interface AnalyticsDateRange {
  preset: DatePreset;
  /** Inclusive `YYYY-MM-DD`; only used (and required together) for `custom`. */
  start?: string;
  end?: string;
}

export function isCustomRange(range: AnalyticsDateRange): boolean {
  return range.preset === 'custom';
}

/** True when every date field the range needs is present. */
export function isValidRange(range: AnalyticsDateRange): boolean {
  if (!isCustomRange(range)) {
    return true;
  }
  return Boolean(range.start && range.end);
}

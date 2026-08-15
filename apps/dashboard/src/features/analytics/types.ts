/**
 * Analytics domain types mirrored from the backend API (Phase 11.3 + 12.4).
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

export interface ResponseMetrics {
  avg_response_time: number | null;
  fastest_response_time: number | null;
  slowest_response_time: number | null;
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

/**
 * Feedback sentiment (Phase 12.5, /api/analytics/feedback).
 * Positive = ratings 4-5, neutral = 3, negative = 1-2.
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
}

export type AnalyticsRange = 7 | 30 | 90;

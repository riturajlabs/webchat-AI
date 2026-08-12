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

export type AnalyticsRange = 7 | 30 | 90;

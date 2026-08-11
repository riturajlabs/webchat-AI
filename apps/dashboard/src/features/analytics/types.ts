/**
 * Analytics domain types mirrored from the backend API (Phase 11.3).
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

export type AnalyticsRange = 7 | 30 | 90;

/**
 * Conversation domain types mirrored from the backend API (Phase 11.2).
 */

export type ConversationStatus = 'answered' | 'awaiting';

export interface ConversationSummary {
  id: string;
  website_id: string;
  visitor_id: string | null;
  title: string;
  message_count: number;
  last_message: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationListResponse {
  items: ConversationSummary[];
  total: number;
  page: number;
  per_page: number;
}

export interface ConversationSource {
  chunk_id?: string;
  url: string;
  title: string;
  score: number;
  citation: number;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources: ConversationSource[];
  response_time: number | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  website_id: string;
  visitor_id: string | null;
  title: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
}

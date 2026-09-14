/**
 * React Query hooks for the conversations feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { ConversationDetail, ConversationListResponse } from './types';

export const conversationsKeys = {
  all: ['conversations'] as const,
  detail: (sessionId: string) => ['conversations', sessionId] as const,
};

/**
 * How often the open conversations list refreshes in the background. Modest
 * polling (page-scoped — it stops as soon as the mount that rendered the query
 * unmounts) so visitor chats added by the backend appear without a manual
 * refresh.
 */
export const CONVERSATIONS_LIST_REFRESH_MS = 8_000;

/**
 * How often an individual conversation is refreshed while it can still be
 * changing. `status` is 'awaiting' while the assistant is (or is about to be)
 * replying and terminal ('answered'/'failed') once the turn is over, so
 * polling stops once the conversation is terminal.
 */
export const CONVERSATION_ACTIVE_REFRESH_MS = 5_000;

/** Conversation statuses that will not change on their own — no more polling. */
const TERMINAL_STATUSES = new Set(['answered', 'failed']);

export interface ConversationsParams {
  page: number;
  perPage: number;
  search?: string;
  websiteId?: string;
}

export function useConversations({ page, perPage, search, websiteId }: ConversationsParams) {
  const searchParams = new URLSearchParams();
  searchParams.set('page', String(page));
  searchParams.set('per_page', String(perPage));
  if (search) {
    searchParams.set('search', search);
  }
  if (websiteId) {
    searchParams.set('website_id', websiteId);
  }
  return useQuery({
    queryKey: ['conversations', 'list', { page, perPage, search, websiteId }],
    queryFn: () => api.get<ConversationListResponse>(`/api/conversations?${searchParams}`),
    refetchInterval: CONVERSATIONS_LIST_REFRESH_MS,
  });
}

export function useConversation(sessionId: string) {
  return useQuery({
    queryKey: conversationsKeys.detail(sessionId),
    queryFn: () =>
      api.get<ConversationDetail>(`/api/conversations/${encodeURIComponent(sessionId)}`),
    enabled: sessionId.length > 0,
    refetchInterval: (query) =>
      query.state.data?.status && TERMINAL_STATUSES.has(query.state.data.status)
        ? false
        : CONVERSATION_ACTIVE_REFRESH_MS,
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.delete<void>(`/api/conversations/${encodeURIComponent(sessionId)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: conversationsKeys.all });
    },
  });
}

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
  });
}

export function useConversation(sessionId: string) {
  return useQuery({
    queryKey: conversationsKeys.detail(sessionId),
    queryFn: () =>
      api.get<ConversationDetail>(`/api/conversations/${encodeURIComponent(sessionId)}`),
    enabled: sessionId.length > 0,
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

/**
 * React Query hooks for the knowledge documents feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { KnowledgeDocumentsResponse, RetryDocumentResponse } from './types';

export const knowledgeKeys = {
  documents: (websiteId: string) => ['knowledge', 'documents', websiteId] as const,
};

export function useKnowledgeDocuments(websiteId: string | null) {
  return useQuery({
    queryKey: knowledgeKeys.documents(websiteId ?? ''),
    queryFn: () =>
      api.get<KnowledgeDocumentsResponse>(`/api/knowledge/websites/${websiteId}/documents`),
    enabled: websiteId !== null,
    // While a website is being embedded, poll so progress bars and the
    // failed list stay current without a manual refresh.
    refetchInterval: (query) =>
      (query.state.data?.summary.processing ?? 0) > 0 ||
      (query.state.data?.summary.pending ?? 0) > 0
        ? 3000
        : false,
  });
}

export function useRetryDocument(websiteId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) =>
      api.post<RetryDocumentResponse>(`/api/knowledge/documents/${documentId}/retry`),
    onSuccess: () => {
      if (websiteId !== null) {
        void queryClient.invalidateQueries({ queryKey: knowledgeKeys.documents(websiteId) });
      }
    },
  });
}

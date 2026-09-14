/**
 * React Query hooks for the knowledge documents feature (00-AI-Development-Rules §14).
 */

import { useMemo } from 'react';
import { useMutation, useQuery, useQueries, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { Website } from '@/features/websites/types';

import { deriveKnowledgeReadiness, knowledgePollIntervalMs } from './status';
import type {
  KnowledgeDocumentsResponse,
  KnowledgeDocumentSummary,
  RetryDocumentResponse,
} from './types';

export const knowledgeKeys = {
  documents: (websiteId: string) => ['knowledge', 'documents', websiteId] as const,
};

export function summaryFromQueryState(data: unknown): KnowledgeDocumentSummary | null {
  if (data !== null && typeof data === 'object' && 'summary' in data) {
    return (data as KnowledgeDocumentsResponse).summary;
  }
  return null;
}

/**
 * Shared document-query configuration. `useKnowledgeDocuments` and the
 * all-sites `useKnowledgeReadinessForSites` use the same keys/settings so a
 * website's documents are fetched exactly once no matter how many surfaces
 * render it.
 */
export function knowledgeDocumentsOptions(websiteId: string | null) {
  return {
    queryKey: knowledgeKeys.documents(websiteId ?? ''),
    queryFn: () =>
      api.get<KnowledgeDocumentsResponse>(`/api/knowledge/websites/${websiteId}/documents`),
    enabled: websiteId !== null,
    // While the website is being embedded, poll so per-document progress (and
    // the derived website truth) stays current. Stops once the pipeline drains.
    refetchInterval: (query: { state: { data: unknown } }) =>
      knowledgePollIntervalMs(summaryFromQueryState(query.state.data)),
  };
}

export function useKnowledgeDocuments(websiteId: string | null) {
  return useQuery(knowledgeDocumentsOptions(websiteId));
}

type ReadinessSource = Pick<Website, 'id' | 'status' | 'knowledge_status'>;

/**
 * Truthful knowledge readiness for a single website, derived from the
 * per-document summary instead of the prematurely-`ready` `knowledge_status`.
 */
export function useKnowledgeReadiness(website: ReadinessSource) {
  const query = useKnowledgeDocuments(website.id);
  const readiness = deriveKnowledgeReadiness(summaryFromQueryState(query.data), website);
  return { query, readiness };
}

export interface SiteKnowledgeReadiness {
  site: Website;
  readiness: ReturnType<typeof deriveKnowledgeReadiness>;
}

/**
 * Derived readiness for every website in a list. Uses `useQueries` so the hook
 * count stays stable (no hooks-in-a-loop) while still fetching each site's
 * documents through the same cache keys as `useKnowledgeDocuments`.
 */
export function useKnowledgeReadinessForSites(sites: Website[]): SiteKnowledgeReadiness[] {
  const results = useQueries({
    queries: sites.map((site) => knowledgeDocumentsOptions(site.id)),
  });
  return useMemo(
    () =>
      sites.map((site, index) => ({
        site,
        readiness: deriveKnowledgeReadiness(summaryFromQueryState(results[index]?.data), site),
      })),
    [sites, results],
  );
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

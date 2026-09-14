/**
 * Pure readiness logic for the knowledge/embedding pipeline.
 *
 * The backend's persisted `website.knowledge_status` is set to `ready` as soon
 * as the first chunk exists (`_refresh_website`), even while sibling documents
 * are still pending/processing/rate-limited. So a truthful UI must derive a
 * website's real readiness from the **per-document** summary returned by
 * `GET /api/knowledge/websites/{id}/documents`, never from the website status
 * alone. These helpers are the single source of that derivation and are unit
 * tested independently of any component.
 */

import type { Website } from '@/features/websites/types';
import type { KnowledgeStatus } from '@/features/websites/types';

import type { KnowledgeDocumentSummary } from './types';

export const KNOWLEDGE_POLL_INTERVAL_MS = 3_000;

/**
 * The knowledge pipeline is still active (not yet terminal) when any document
 * is non-terminal. `rate_limited` is a real backend state (a deferred retry is
 * still pending) and must keep the pipeline "active" exactly like pending.
 */
export function isKnowledgePipelineActive(
  summary: KnowledgeDocumentSummary | null | undefined,
): boolean {
  if (!summary) {
    return false;
  }
  return summary.pending > 0 || summary.processing > 0 || summary.rate_limited > 0;
}

/** React Query `refetchInterval` value: poll only while the pipeline is active. */
export function knowledgePollIntervalMs(
  summary: KnowledgeDocumentSummary | null | undefined,
): number | false {
  return isKnowledgePipelineActive(summary) ? KNOWLEDGE_POLL_INTERVAL_MS : false;
}

export interface KnowledgeReadiness {
  /** True once the per-document summary has actually been observed. */
  known: boolean;
  /** True while any document is pending/processing/rate-limited. */
  isEmbedding: boolean;
  /** True only when everything drained AND the crawl itself is done. */
  isReady: boolean;
  isFailed: boolean;
  /** True when every document reached a terminal state. */
  isSettled: boolean;
  status: KnowledgeStatus | null;
  summary: KnowledgeDocumentSummary | null;
}

type ReadinessSource = Pick<Website, 'id' | 'status' | 'knowledge_status'>;

export function deriveKnowledgeReadiness(
  summary: KnowledgeDocumentSummary | null,
  website: ReadinessSource,
): KnowledgeReadiness {
  if (summary === null) {
    // No per-document data observed yet: never claim "ready". Only states the
    // list API itself reports are echoed back, so a prematurely-`ready`
    // backend value can never render green before the documents confirm it.
    const fallback = website.knowledge_status;
    return {
      known: false,
      isEmbedding: fallback === 'processing',
      isReady: false,
      isFailed: fallback === 'failed',
      isSettled: false,
      status: fallback,
      summary: null,
    };
  }
  if (summary.total === 0) {
    // Zero documents: nothing observable to contradict the persisted status.
    // Embedding that has not produced documents yet still reads as active when
    // the backend reports `processing`.
    const fallback = website.knowledge_status;
    return {
      known: true,
      isEmbedding: fallback === 'processing',
      isReady: website.status === 'ready' && fallback === 'ready',
      isFailed: fallback === 'failed',
      isSettled: fallback !== 'processing',
      status: fallback,
      summary,
    };
  }
  if (isKnowledgePipelineActive(summary)) {
    return {
      known: true,
      isEmbedding: true,
      isReady: false,
      isFailed: false,
      isSettled: false,
      status: 'processing',
      summary,
    };
  }
  if (summary.completed > 0) {
    return {
      known: true,
      isEmbedding: false,
      isReady: website.status === 'ready',
      isFailed: false,
      isSettled: true,
      status: 'ready',
      summary,
    };
  }
  if (summary.failed > 0) {
    return {
      known: true,
      isEmbedding: false,
      isReady: false,
      isFailed: true,
      isSettled: true,
      status: 'failed',
      summary,
    };
  }
  return {
    known: true,
    isEmbedding: false,
    isReady: false,
    isFailed: false,
    isSettled: true,
    status: 'none',
    summary,
  };
}

export const UNKNOWN_READINESS: KnowledgeReadiness = {
  known: false,
  isEmbedding: false,
  isReady: false,
  isFailed: false,
  isSettled: false,
  status: null,
  summary: null,
};

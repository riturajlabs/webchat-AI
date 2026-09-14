/**
 * Knowledge document types mirrored from the backend knowledge API.
 *
 * Each crawled page maps to one `KnowledgeDocument` whose `status` is one of
 * the pipeline states (pending/processing/completed/failed). Failed documents
 * carry a `failure_reason` and retry accounting so the dashboard can surface
 * what went wrong and let the owner re-process a page manually.
 */

export type KnowledgeDocumentStatus =
  'pending' | 'processing' | 'completed' | 'failed' | 'rate_limited';

/** A document that is permanently terminal and will not move again on its own. */
export const TERMINAL_KNOWLEDGE_STATUSES: ReadonlySet<KnowledgeDocumentStatus> = new Set([
  'completed',
  'failed',
]);

export function isKnowledgeDocumentTerminal(status: KnowledgeDocumentStatus): boolean {
  return TERMINAL_KNOWLEDGE_STATUSES.has(status);
}

export interface KnowledgeDocument {
  id: string;
  website_id: string;
  url: string;
  title: string;
  status: KnowledgeDocumentStatus;
  failure_reason: string | null;
  retry_count: number;
  last_attempt_at: string | null;
  chunks: number;
}

export interface KnowledgeDocumentSummary {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  /** Docs awaiting a deferred retry after provider quota/rate-limit rejection (non-terminal). */
  rate_limited: number;
}

export interface KnowledgeDocumentsResponse {
  website_id: string;
  summary: KnowledgeDocumentSummary;
  documents: KnowledgeDocument[];
}

export interface RetryDocumentResponse {
  document_id: string;
  website_id: string;
  status: string;
}

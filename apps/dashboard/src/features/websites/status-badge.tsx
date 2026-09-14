import { Loader2 } from 'lucide-react';

import { StatusBadge as StatusBadgeBase } from '@/components/ui/status-badge';
import { cn } from '@/lib/utils';

import type { KnowledgeReadiness } from '@/features/knowledge/status';

import { isChatReady, isEmbeddingInProgress } from './types';
import type { Website, WebsiteStatus } from './types';

const STATUS_STYLES: Record<WebsiteStatus, string> = {
  pending: 'bg-muted text-muted-foreground',
  crawling: 'bg-blue-100 text-blue-800',
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

const PILL_STYLES =
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium';

export function StatusBadge({ status }: { status: WebsiteStatus }) {
  return <StatusBadgeBase className={STATUS_STYLES[status]}>{status}</StatusBadgeBase>;
}

function GeneratingEmbeddingsPill() {
  return (
    <span
      className={cn(
        PILL_STYLES,
        'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
      )}
    >
      <Loader2 className="size-3 animate-spin" aria-hidden="true" />
      Generating embeddings…
    </span>
  );
}

function CheckingPill() {
  return (
    <span className={cn(PILL_STYLES, 'bg-muted text-muted-foreground')}>
      <Loader2 className="size-3 animate-spin" aria-hidden="true" />
      Checking…
    </span>
  );
}

interface WebsiteStatusBadgeProps {
  website: Website;
  /**
   * Derived per-document readiness when available. When omitted (legacy call
   * sites) the badge falls back to trusting the website's persisted status.
   */
  readiness?: KnowledgeReadiness;
}

/**
 * Readiness pill for the crawl/knowledge lifecycle of a website.
 * A plain green "ready" is only shown once BOTH the crawl AND the knowledge
 * base are confirmed finished. When per-document readiness data is supplied it
 * is the source of truth: the backend's persisted `knowledge_status` can be
 * `ready` while sibling documents are still being embedded, so the badge never
 * turns green from that flag alone — it shows an amber "Generating
 * embeddings…" while any document is pending/processing/rate-limited and a
 * muted "Checking…" before the documents have been observed.
 */
export function WebsiteStatusBadge({ website, readiness }: WebsiteStatusBadgeProps) {
  if (website.status === 'failed') {
    return <StatusBadge status="failed" />;
  }

  if (readiness === undefined) {
    // Legacy path without per-document data: keep the previous truthful rules.
    if (isEmbeddingInProgress(website)) {
      return <GeneratingEmbeddingsPill />;
    }
    if (isChatReady(website)) {
      return <StatusBadge status="ready" />;
    }
    return <StatusBadge status={website.status} />;
  }

  if (readiness.isEmbedding) {
    return <GeneratingEmbeddingsPill />;
  }
  if (readiness.known) {
    if (readiness.isReady) {
      return <StatusBadge status="ready" />;
    }
    if (readiness.isFailed) {
      return <StatusBadge status="failed" />;
    }
  }
  if (!readiness.known) {
    // The documents have not been observed yet — never read as ready/embedding.
    return <CheckingPill />;
  }
  return <StatusBadge status={website.status} />;
}

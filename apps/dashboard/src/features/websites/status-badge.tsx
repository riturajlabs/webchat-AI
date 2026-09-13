import { Loader2 } from 'lucide-react';

import { StatusBadge as StatusBadgeBase } from '@/components/ui/status-badge';
import { cn } from '@/lib/utils';

import { isChatReady, isEmbeddingInProgress } from './types';
import type { Website, WebsiteStatus } from './types';

const STATUS_STYLES: Record<WebsiteStatus, string> = {
  pending: 'bg-muted text-muted-foreground',
  crawling: 'bg-blue-100 text-blue-800',
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

export function StatusBadge({ status }: { status: WebsiteStatus }) {
  return <StatusBadgeBase className={STATUS_STYLES[status]}>{status}</StatusBadgeBase>;
}

/**
 * Readiness pill for the crawl/knowledge lifecycle of a website.
 * A plain green "ready" is only shown once BOTH the crawl and the knowledge
 * base are finished (`status === 'ready' && knowledge_status === 'ready'`).
 * While the crawl is complete but embedding is still running the pill switches
 * to an amber "Generating embeddings…" state so the UI never advertises a site
 * as fully ready for chat before its knowledge is ready.
 */
export function WebsiteStatusBadge({ website }: { website: Website }) {
  if (website.status === 'failed') {
    return <StatusBadge status="failed" />;
  }
  if (isEmbeddingInProgress(website)) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium',
          'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
        )}
      >
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        Generating embeddings…
      </span>
    );
  }
  if (isChatReady(website)) {
    return <StatusBadge status="ready" />;
  }
  return <StatusBadge status={website.status} />;
}

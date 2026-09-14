import { Loader2 } from 'lucide-react';

import type { KnowledgeStatus } from './types';
import { cn } from '@/lib/utils';

const KNOWLEDGE_STYLES: Record<KnowledgeStatus, string> = {
  none: 'bg-muted text-muted-foreground',
  processing: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  ready: 'bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300',
};

interface KnowledgeBadgeProps {
  /** Derived knowledge status; `null` when the per-document data has not loaded. */
  status: KnowledgeStatus | null;
  /** While any document is pending/processing/rate-limited the badge shows the amber embedding state. */
  embedding?: boolean;
}

/**
 * Small knowledge-state pill. Never renders a green "ready" unless the status
 * is actually `ready`; while embedding runs it switches to the amber
 * "Generating embeddings…" state, and while the per-document data has not been
 * observed (`status === null`) it shows a muted "Checking…" instead of trusting
 * the backend's prematurely-`ready` website flag.
 */
export function KnowledgeBadge({ status, embedding = false }: KnowledgeBadgeProps) {
  if (embedding) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
          'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
        )}
      >
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        Generating embeddings…
      </span>
    );
  }
  if (status === null) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
          'bg-muted text-muted-foreground',
        )}
      >
        Checking…
      </span>
    );
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize',
        KNOWLEDGE_STYLES[status],
      )}
    >
      {status}
    </span>
  );
}

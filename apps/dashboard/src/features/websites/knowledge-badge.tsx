import type { KnowledgeStatus } from './types';
import { cn } from '@/lib/utils';

const KNOWLEDGE_STYLES: Record<KnowledgeStatus, string> = {
  none: 'bg-muted text-muted-foreground',
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

export function KnowledgeBadge({ status }: { status: KnowledgeStatus }) {
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

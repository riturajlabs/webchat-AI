import { cn } from '@/lib/utils';

import type { WebsiteStatus } from './types';

const STATUS_STYLES: Record<WebsiteStatus, string> = {
  pending: 'bg-muted text-muted-foreground',
  crawling: 'bg-blue-100 text-blue-800',
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

export function StatusBadge({ status }: { status: WebsiteStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        STATUS_STYLES[status],
      )}
    >
      {status}
    </span>
  );
}

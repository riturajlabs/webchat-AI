import Link from 'next/link';
import { MessageSquareText } from 'lucide-react';

import { cn } from '@/lib/utils';

import { formatDateTime, formatMessageCount, visitorLabel } from './format';
import { ConversationStatusBadge } from './status-badge';
import type { ConversationSummary } from './types';

export function ConversationListItem({
  item,
  websiteName,
}: {
  item: ConversationSummary;
  websiteName?: string;
}) {
  return (
    <li>
      <Link
        href={`/conversations/${encodeURIComponent(item.id)}`}
        className="flex flex-col gap-2 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex items-center justify-between gap-3">
          <span className="truncate font-medium">{visitorLabel(item.visitor_id)}</span>
          <ConversationStatusBadge status={item.status} />
        </div>
        <p
          className={cn(
            'truncate text-sm',
            item.last_message ? '' : 'italic text-muted-foreground',
          )}
        >
          {item.last_message || item.title}
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{formatDateTime(item.updated_at)}</span>
          <span className="truncate">{websiteName ?? item.website_id}</span>
          <span className="inline-flex items-center gap-1">
            <MessageSquareText className="size-3.5" aria-hidden="true" />
            {formatMessageCount(item.message_count)}
          </span>
        </div>
      </Link>
    </li>
  );
}

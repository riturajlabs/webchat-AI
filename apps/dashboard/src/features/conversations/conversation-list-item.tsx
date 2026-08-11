import Link from 'next/link';
import { MessageSquareText } from 'lucide-react';

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
        className="grid gap-2 rounded-lg border bg-card p-4 shadow-sm transition-colors hover:bg-accent/50 md:grid-cols-[minmax(0,2fr)_8rem_8rem_5.5rem_auto] md:items-center"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate font-medium">{visitorLabel(item.visitor_id)}</span>
          <span className="truncate text-sm text-muted-foreground" title={item.title}>
            {item.last_message || item.title}
          </span>
        </div>
        <span className="text-sm text-muted-foreground">{formatDateTime(item.created_at)}</span>
        <span className="truncate text-sm text-muted-foreground">
          {websiteName ?? item.website_id}
        </span>
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <MessageSquareText className="size-4" aria-hidden="true" />
          {formatMessageCount(item.message_count)}
        </span>
        <span className="justify-self-start">
          <ConversationStatusBadge status={item.status} />
        </span>
      </Link>
    </li>
  );
}

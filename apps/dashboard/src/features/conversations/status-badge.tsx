import { cn } from '@/lib/utils';

import { STATUS_LABELS, STATUS_STYLES } from './format';
import type { ConversationStatus } from './types';

export function ConversationStatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        STATUS_STYLES[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

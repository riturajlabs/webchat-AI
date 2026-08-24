import { StatusBadge } from '@/components/ui/status-badge';

import { STATUS_LABELS, STATUS_STYLES } from './format';
import type { ConversationStatus } from './types';

export function ConversationStatusBadge({ status }: { status: ConversationStatus }) {
  return <StatusBadge className={STATUS_STYLES[status]}>{STATUS_LABELS[status]}</StatusBadge>;
}

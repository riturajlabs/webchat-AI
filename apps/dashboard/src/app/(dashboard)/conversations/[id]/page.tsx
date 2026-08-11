import type { Metadata } from 'next';

import { ConversationDetailPage } from '@/features/conversations/conversation-detail';

export const metadata: Metadata = {
  title: 'Conversation',
};

export default async function ConversationDetailRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ConversationDetailPage sessionId={id} />;
}

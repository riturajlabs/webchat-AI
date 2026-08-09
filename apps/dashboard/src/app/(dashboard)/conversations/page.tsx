import type { Metadata } from 'next';

import { ConversationsPage } from '@/features/conversations/conversations-page';

export const metadata: Metadata = {
  title: 'Conversations',
};

export default function ConversationsPageRoute() {
  return <ConversationsPage />;
}

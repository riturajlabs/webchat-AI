import type { Metadata } from 'next';

import { KnowledgePage as KnowledgeFeature } from '@/features/knowledge/knowledge-page';

export const metadata: Metadata = {
  title: 'Knowledge Base',
};

export default function KnowledgePage() {
  return <KnowledgeFeature />;
}

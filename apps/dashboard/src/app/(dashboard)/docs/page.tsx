import type { Metadata } from 'next';

import { DocsPage } from '@/features/docs/docs-page';

export const metadata: Metadata = {
  title: 'Developer Documentation',
};

export default function DeveloperDocsRoute() {
  return <DocsPage />;
}

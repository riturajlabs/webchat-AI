import type { Metadata } from 'next';

import { WebsiteList } from '@/features/websites/website-list';

export const metadata: Metadata = {
  title: 'Websites',
};

export default function WebsitesPage() {
  return <WebsiteList />;
}

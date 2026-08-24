import type { Metadata } from 'next';

import { DashboardHome } from '@/features/dashboard/dashboard-home';

export const metadata: Metadata = {
  title: 'Dashboard',
  description:
    'Overview of your WebChat AI assistants: connected websites, knowledge coverage, crawl status, and system health.',
};

export default function DashboardPage() {
  return <DashboardHome />;
}

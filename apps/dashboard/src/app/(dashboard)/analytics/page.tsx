import type { Metadata } from 'next';

import { AnalyticsPage } from '@/features/analytics/analytics-page';

export const metadata: Metadata = {
  title: 'Analytics',
};

export default function AnalyticsPageRoute() {
  return <AnalyticsPage />;
}

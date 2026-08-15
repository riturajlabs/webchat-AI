import type { Metadata } from 'next';

import { UsagePage } from '@/features/usage/usage-page';

export const metadata: Metadata = {
  title: 'Usage & Billing',
};

export default function UsagePageRoute() {
  return <UsagePage />;
}

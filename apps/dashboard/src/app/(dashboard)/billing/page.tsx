import type { Metadata } from 'next';

import { BillingPage } from '@/features/billing/billing-page';

export const metadata: Metadata = {
  title: 'Billing',
};

export default function BillingPageRoute() {
  return <BillingPage />;
}

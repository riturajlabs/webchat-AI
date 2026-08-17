import type { Metadata } from 'next';
import { Suspense } from 'react';

import { BillingPage } from '@/features/billing/billing-page';

export const metadata: Metadata = {
  title: 'Billing',
};

export default function BillingPageRoute() {
  return (
    <Suspense>
      <BillingPage />
    </Suspense>
  );
}

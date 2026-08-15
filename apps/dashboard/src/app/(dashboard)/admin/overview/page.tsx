import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminOverviewPage } from '@/features/admin/overview-page';

export const metadata: Metadata = {
  title: 'Admin Overview',
};

export default function AdminOverviewRoute() {
  return (
    <AdminGuard>
      <AdminOverviewPage />
    </AdminGuard>
  );
}

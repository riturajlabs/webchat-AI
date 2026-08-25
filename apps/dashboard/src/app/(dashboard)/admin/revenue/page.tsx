import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';
import { RevenuePanel } from '@/features/admin/revenue-panel';

export const metadata: Metadata = {
  title: 'Admin Revenue',
};

export default function AdminRevenueRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="Revenue" description="Billing and subscription revenue." />
        <AdminNav />
        <RevenuePanel />
      </div>
    </AdminGuard>
  );
}

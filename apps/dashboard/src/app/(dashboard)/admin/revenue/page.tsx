import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';
import { RevenuePanel } from '@/features/admin/revenue-panel';

export const metadata: Metadata = {
  title: 'Admin Revenue',
};

export default function AdminRevenueRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Revenue</h1>
          <p className="text-sm text-muted-foreground">Billing and subscription revenue.</p>
        </div>
        <AdminNav />
        <RevenuePanel />
      </div>
    </AdminGuard>
  );
}

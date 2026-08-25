import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';
import { TenantPanel } from '@/features/admin/tenant-panel';

export const metadata: Metadata = {
  title: 'Admin Tenants',
};

export default function AdminTenantsRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="Tenants" description="Manage workspaces, plans, and status." />
        <AdminNav />
        <TenantPanel />
      </div>
    </AdminGuard>
  );
}

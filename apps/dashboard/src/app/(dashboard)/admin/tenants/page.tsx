import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';
import { TenantPanel } from '@/features/admin/tenant-panel';

export const metadata: Metadata = {
  title: 'Admin Tenants',
};

export default function AdminTenantsRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Tenants</h1>
          <p className="text-sm text-muted-foreground">Manage workspaces, plans, and status.</p>
        </div>
        <AdminNav />
        <TenantPanel />
      </div>
    </AdminGuard>
  );
}

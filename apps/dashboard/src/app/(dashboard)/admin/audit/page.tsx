import type { Metadata } from 'next';

import { AdminAuditPanel } from '@/features/admin/admin-audit-panel';
import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';

export const metadata: Metadata = {
  title: 'Admin Audit',
};

export default function AdminAuditRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Audit</h1>
          <p className="text-sm text-muted-foreground">Platform operator action trail.</p>
        </div>
        <AdminNav />
        <AdminAuditPanel />
      </div>
    </AdminGuard>
  );
}

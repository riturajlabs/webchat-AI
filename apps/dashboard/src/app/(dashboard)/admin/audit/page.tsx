import type { Metadata } from 'next';

import { AdminAuditPanel } from '@/features/admin/admin-audit-panel';
import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';

export const metadata: Metadata = {
  title: 'Admin Audit',
};

export default function AdminAuditRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="Audit" description="Platform operator action trail." />
        <AdminNav />
        <AdminAuditPanel />
      </div>
    </AdminGuard>
  );
}

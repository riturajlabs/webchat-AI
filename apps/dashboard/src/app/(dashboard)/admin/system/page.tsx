import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';
import { SystemPanel } from '@/features/admin/system-panel';

export const metadata: Metadata = {
  title: 'Admin System',
};

export default function AdminSystemRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="System" description="Dependency probes and collection counts." />
        <AdminNav />
        <SystemPanel />
      </div>
    </AdminGuard>
  );
}

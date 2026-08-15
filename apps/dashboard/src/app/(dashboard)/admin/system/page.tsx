import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';
import { SystemPanel } from '@/features/admin/system-panel';

export const metadata: Metadata = {
  title: 'Admin System',
};

export default function AdminSystemRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">System</h1>
          <p className="text-sm text-muted-foreground">Dependency probes and collection counts.</p>
        </div>
        <AdminNav />
        <SystemPanel />
      </div>
    </AdminGuard>
  );
}

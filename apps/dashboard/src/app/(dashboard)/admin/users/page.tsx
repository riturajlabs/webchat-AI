import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';
import { UserPanel } from '@/features/admin/user-panel';

export const metadata: Metadata = {
  title: 'Admin Users',
};

export default function AdminUsersRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-sm text-muted-foreground">Cross-tenant user management.</p>
        </div>
        <AdminNav />
        <UserPanel />
      </div>
    </AdminGuard>
  );
}

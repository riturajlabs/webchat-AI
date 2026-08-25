import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';
import { UserPanel } from '@/features/admin/user-panel';

export const metadata: Metadata = {
  title: 'Admin Users',
};

export default function AdminUsersRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="Users" description="Cross-tenant user management." />
        <AdminNav />
        <UserPanel />
      </div>
    </AdminGuard>
  );
}

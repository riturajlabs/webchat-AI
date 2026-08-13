import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminPage } from '@/features/admin/admin-page';

export const metadata: Metadata = {
  title: 'Admin',
};

export default function AdminRoute() {
  return (
    <AdminGuard>
      <AdminPage />
    </AdminGuard>
  );
}

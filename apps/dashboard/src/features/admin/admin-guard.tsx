'use client';

import { ShieldX } from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { EmptyState } from '@/components/ui/empty-state';
import { PageSkeleton } from '@/components/ui/page-skeleton';

/**
 * Admin-only gate for the admin routes (Phase 15).
 * The backend independently enforces `role=super_admin` on every /api/admin
 * endpoint (403 otherwise); this gate only hides the UI for non-super-admins.
 */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { user, status } = useAuth();

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-4xl">
          <PageSkeleton />
        </div>
      </div>
    );
  }

  if (user?.role !== 'super_admin') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyState
          icon={ShieldX}
          title="Admin access required"
          description="You need a super admin role to view platform operations."
          actionLabel="Back to dashboard"
          onAction={() => {
            window.location.assign('/dashboard');
          }}
        />
      </div>
    );
  }

  return <>{children}</>;
}

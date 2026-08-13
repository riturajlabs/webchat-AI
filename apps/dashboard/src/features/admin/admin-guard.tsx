'use client';

import { ShieldX } from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Admin-only gate for the admin route (Phase 12.5, ADR-006).
 * The backend independently enforces `role=admin` on every /api/admin
 * endpoint (403 otherwise); this gate only hides the UI for non-admins.
 */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { user, status } = useAuth();

  if (status === 'loading') {
    return null;
  }

  if (user?.role !== 'admin') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyState
          icon={ShieldX}
          title="Admin access required"
          description="You need an admin role to view platform operations."
          actionLabel="Back to dashboard"
          onAction={() => {
            window.location.assign('/');
          }}
        />
      </div>
    );
  }

  return <>{children}</>;
}

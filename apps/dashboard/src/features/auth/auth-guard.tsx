'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';

import { useAuth } from '@/features/auth/auth-context';
import { PageSkeleton } from '@/components/ui/page-skeleton';

export function AuthGuard({ children }: { children: ReactNode }) {
  const { isAuthenticated, status } = useAuth();
  const router = useRouter();
  const [redirected, setRedirected] = useState(false);

  useEffect(() => {
    if (status === 'ready' && !isAuthenticated && !redirected) {
      setRedirected(true);
      const loginUrl = new URL('/login', window.location.origin);
      loginUrl.searchParams.set('redirect', window.location.pathname + window.location.search);
      router.replace(loginUrl.pathname + loginUrl.search);
    }
  }, [status, isAuthenticated, redirected, router]);

  // Show skeleton while auth state resolves AND while the redirect effect
  // runs.  This avoids a blank flash and gives visual feedback that the app
  // is loading / redirecting.
  if (status !== 'ready' || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-4xl">
          <PageSkeleton />
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

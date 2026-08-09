'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';

import { useAuth } from '@/features/auth/auth-context';

export function AuthGuard({ children }: { children: ReactNode }) {
  const { isAuthenticated, status } = useAuth();
  const router = useRouter();
  const [redirected, setRedirected] = useState(false);

  useEffect(() => {
    if (status === 'ready' && !isAuthenticated && !redirected) {
      setRedirected(true);
      const redirect = encodeURIComponent(window.location.pathname + window.location.search);
      router.replace(`/login?redirect=${redirect}`);
    }
  }, [status, isAuthenticated, redirected, router]);

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}

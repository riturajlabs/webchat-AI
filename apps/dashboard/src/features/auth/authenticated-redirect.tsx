'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useAuth } from '@/features/auth/auth-context';

/**
 * Keeps authenticated users out of the sign-in / sign-up flows by sending them
 * straight to the dashboard once auth state resolves.
 */
export function AuthenticatedRedirect() {
  const { isAuthenticated, status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === 'ready' && isAuthenticated) {
      router.replace('/dashboard');
    }
  }, [isAuthenticated, status, router]);

  return null;
}

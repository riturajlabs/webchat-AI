'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';

import type { MessageResponse } from './types';

export function VerifyEmailForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function verify() {
      if (!token) {
        setError('This verification link is missing its token.');
        setIsPending(false);
        return;
      }
      try {
        const response = await api.post<MessageResponse>('/api/auth/verify-email', { token });
        if (!cancelled) {
          setMessage(response.message);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Verification failed.');
        }
      } finally {
        if (!cancelled) {
          setIsPending(false);
        }
      }
    }
    void verify();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="flex flex-col gap-4">
      {isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          Verifying your email…
        </p>
      ) : null}

      {message ? (
        <p
          role="status"
          className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-900 dark:bg-green-500/10 dark:text-green-300"
        >
          {message}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {!isPending ? (
        <Button asChild>
          <Link href="/login">Back to sign in</Link>
        </Button>
      ) : null}
    </div>
  );
}

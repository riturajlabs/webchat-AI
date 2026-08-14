'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import type { MessageResponse } from './types';

export function ResendVerificationForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState(searchParams.get('email') ?? '');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || isPending) {
      return;
    }
    setIsPending(true);
    setError(null);
    setMessage(null);
    try {
      const response = await api.post<MessageResponse>('/api/auth/resend-verification', {
        email: email.trim().toLowerCase(),
      });
      setMessage(response.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send the verification link.');
    } finally {
      setIsPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Check your inbox for the verification link we sent when you created your account.
        Didn&apos;t receive it? Enter your email and we&apos;ll send a fresh one.
      </p>

      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="verify-email">Email</Label>
          <Input
            id="verify-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
        </div>

        {message ? (
          <p role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-900">
            {message}
          </p>
        ) : null}

        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <Button type="submit" disabled={isPending}>
          {isPending ? 'Sending link…' : 'Resend verification link'}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already verified?{' '}
        <Link
          href="/login"
          className="font-medium text-foreground underline-offset-4 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}

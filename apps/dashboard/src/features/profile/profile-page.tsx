'use client';

import { CalendarDays, CircleUser, Loader2, Mail, Send, ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/auth-context';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

function EmailVerificationCard() {
  const { user } = useAuth();
  const [isPending, setIsPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentUser = user;
  if (!currentUser) {
    return null;
  }
  const email = currentUser.email;
  const isVerified = currentUser.email_verified;

  async function sendVerificationEmail() {
    if (isPending) {
      return;
    }
    setIsPending(true);
    setError(null);
    setMessage(null);
    try {
      await api.post('/api/auth/resend-verification', { email });
      setMessage('Verification email sent. Please check your inbox.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send the verification email.');
    } finally {
      setIsPending(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <CardTitle>Email verification</CardTitle>
          <CardDescription>Confirm your email address to secure your account.</CardDescription>
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset',
            isVerified
              ? 'bg-green-50 text-green-700 ring-green-200 dark:bg-green-500/10 dark:text-green-400 dark:ring-green-500/30'
              : 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:ring-amber-500/30',
          )}
        >
          <span
            className={cn('size-1.5 rounded-full', isVerified ? 'bg-green-600' : 'bg-amber-600')}
            aria-hidden="true"
          />
          {isVerified ? 'Verified' : 'Pending Verification'}
        </span>
      </CardHeader>
      <CardContent>
        {isVerified ? (
          <div className="flex items-start gap-3 rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-500/30 dark:bg-green-500/10">
            <ShieldCheck
              className="mt-0.5 size-5 shrink-0 text-green-700 dark:text-green-400"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-green-800 dark:text-green-300">
              Your email address is verified. You are all set.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
              <Mail
                className="mt-0.5 size-5 shrink-0 text-amber-700 dark:text-amber-400"
                aria-hidden="true"
              />
              <p className="text-sm text-amber-900 dark:text-amber-200">
                A verification email was sent when you signed up. Confirm your address to receive
                important account notifications and security alerts.
              </p>
            </div>

            {message ? (
              <p
                role="status"
                className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-900 dark:bg-green-500/10 dark:text-green-300"
              >
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

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                onClick={() => void sendVerificationEmail()}
                disabled={isPending}
              >
                {isPending ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="size-4" aria-hidden="true" />
                )}
                {isPending ? 'Sending…' : 'Send Verification Email'}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => void sendVerificationEmail()}
                disabled={isPending}
              >
                Resend Email
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Read-only profile: the backend exposes the current user via /api/auth/me
 * (loaded by AuthProvider) but has no profile-update endpoint yet, so editing
 * is intentionally not offered (docs/06 Phase 7).
 */
export function ProfilePage() {
  const { user, status } = useAuth();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Profile</h1>
        <p className="text-sm text-muted-foreground">Your account details.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Account information</CardTitle>
          <CardDescription>Details from your signed-in account.</CardDescription>
        </CardHeader>
        <CardContent>
          {status === 'loading' || !user ? (
            <div className="flex flex-col gap-4">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-5 w-64" />
              <Skeleton className="h-5 w-40" />
            </div>
          ) : (
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CircleUser className="size-4" aria-hidden="true" />
                  Name
                </dt>
                <dd className="mt-1 text-sm font-medium">{user.name}</dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Mail className="size-4" aria-hidden="true" />
                  Email
                </dt>
                <dd className="mt-1 text-sm font-medium">{user.email}</dd>
              </div>
              <div>
                <dt className="text-sm text-muted-foreground">Role</dt>
                <dd className="mt-1 text-sm font-medium capitalize">{user.role}</dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-sm text-muted-foreground">
                  <ShieldCheck className="size-4" aria-hidden="true" />
                  Email status
                </dt>
                <dd className="mt-1 text-sm font-medium">
                  {user.email_verified ? '✓ Email verified' : '❌ Email not verified'}
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CalendarDays className="size-4" aria-hidden="true" />
                  Member since
                </dt>
                <dd className="mt-1 text-sm font-medium">{formatDate(user.created_at)}</dd>
              </div>
            </dl>
          )}
        </CardContent>
      </Card>

      <EmailVerificationCard />

      <p className="text-sm text-muted-foreground">
        Profile editing will be available in a future phase.
      </p>
    </div>
  );
}

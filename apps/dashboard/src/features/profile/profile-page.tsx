'use client';

import { CalendarDays, CircleUser, Mail } from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
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
                <dt className="text-sm text-muted-foreground">Email verified</dt>
                <dd className="mt-1 text-sm font-medium">{user.email_verified ? 'Yes' : 'No'}</dd>
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

      <p className="text-sm text-muted-foreground">
        Profile editing will be available in a future phase.
      </p>
    </div>
  );
}

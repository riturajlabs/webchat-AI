'use client';

import Link from 'next/link';
import { ShieldAlert, X } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';

const dismissedKey = (userId: string) => `webchat:verification-banner-dismissed:${userId}`;

function isDismissed(userId: string): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    return window.localStorage.getItem(dismissedKey(userId)) === '1';
  } catch {
    return false;
  }
}

/**
 * Non-blocking banner shown to signed-in accounts whose email has not been
 * verified. Login is always allowed (the verification gate was removed), so
 * this is the persistent reminder to verify; the profile page hosts the full
 * verification section. Dismissing the banner hides it on this device (per
 * user), without removing the ability to verify from the profile page.
 */
export function VerificationReminder() {
  const { user } = useAuth();
  const [userDismissed, setUserDismissed] = useState(false);

  if (!user || user.email_verified) {
    return null;
  }

  const userId = user.id;

  if (userDismissed || isDismissed(userId)) {
    return null;
  }

  function handleDismiss() {
    setUserDismissed(true);
    try {
      window.localStorage.setItem(dismissedKey(userId), '1');
    } catch {
      // Storage unavailable (e.g. private browsing): hide for this session only.
    }
  }

  return (
    <div className="px-4 pt-4 md:px-10">
      <div
        role="status"
        className="flex flex-col gap-4 rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 shadow-sm dark:border-amber-800/60 dark:bg-amber-950/30 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/60">
            <ShieldAlert className="size-4 text-amber-700 dark:text-amber-300" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold text-amber-900 dark:text-amber-50">
              Your email is not verified. Please verify your email.
            </p>
            <p className="mt-1 text-sm text-amber-800 dark:text-amber-200">
              Confirm your address to secure your account and receive important updates.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pl-12 sm:pl-0">
          <Button asChild size="sm">
            <Link href="/profile">Verify Email</Link>
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-amber-800 hover:bg-amber-100 hover:text-amber-900 dark:text-amber-200 dark:hover:bg-amber-900/40 dark:hover:text-amber-50"
            onClick={handleDismiss}
          >
            <X className="size-3.5" aria-hidden="true" />
            Dismiss
          </Button>
        </div>
      </div>
    </div>
  );
}

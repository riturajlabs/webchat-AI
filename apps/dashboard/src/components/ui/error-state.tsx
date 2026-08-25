'use client';

import { AlertCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * Shared data-loading error banner: icon, message, and a retry action.
 * Rendered with role="alert" so screen readers announce load failures.
 */
export function ErrorState({
  message = 'Something went wrong.',
  onRetry,
}: {
  message?: string;
  /** Called when the "Try again" button is activated; omit for read-only alerts. */
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
    >
      <p className="flex items-center gap-2 text-sm text-destructive">
        <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
        {message}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

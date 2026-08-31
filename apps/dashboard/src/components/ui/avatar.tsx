'use client';

import { useState } from 'react';

import { cn } from '@/lib/utils';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '?';
  }
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase();
}

/**
 * Shared circular account avatar.
 *
 * Single source for displaying a user's profile photo: render the image when a
 * photo exists, otherwise (or when the image fails to load) fall back to
 * initials. The shell is a fixed-size rounded square so loading the image never
 * causes the surrounding layout to jump.
 */
export function Avatar({
  name,
  avatarUrl,
  className,
}: {
  name?: string | null;
  avatarUrl?: string | null;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(avatarUrl) && !failed;

  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary text-sm font-semibold text-primary-foreground',
        className,
      )}
      aria-hidden="true"
    >
      {showImage ? (
        /* eslint-disable-next-line @next/next/no-img-element -- user-provided avatar data URL */
        <img
          src={avatarUrl as string}
          alt=""
          className="size-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span>{initials(name ?? '?')}</span>
      )}
    </span>
  );
}

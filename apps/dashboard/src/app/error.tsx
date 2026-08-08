'use client';

import { useEffect } from 'react';

import { Button } from '@/components/ui/button';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="font-sans text-2xl font-bold">Something went wrong</h1>
      <p className="max-w-md font-mono text-sm text-muted-foreground">
        An unexpected error occurred while rendering this page.
      </p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}

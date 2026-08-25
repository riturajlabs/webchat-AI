'use client';

import { useEffect } from 'react';
import { TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';

export default function AuthError({
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
    <div className="flex flex-col items-center gap-3 py-2 text-center">
      <TriangleAlert className="size-8 text-destructive" aria-hidden="true" />
      <h1 className="font-sans text-lg font-bold">Something went wrong</h1>
      <p className="text-sm text-muted-foreground">
        An unexpected error occurred while loading this page. Please try again.
      </p>
      <Button onClick={reset} className="mt-1 w-full">
        Try again
      </Button>
    </div>
  );
}

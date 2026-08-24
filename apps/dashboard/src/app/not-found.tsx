import Link from 'next/link';
import { Bot, Compass } from 'lucide-react';

import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Bot className="size-5" aria-hidden="true" />
      </span>
      <div className="flex flex-col items-center gap-3">
        <p className="font-sans text-7xl font-bold tracking-tight">404</p>
        <h1 className="flex items-center gap-2 font-sans text-xl font-semibold">
          <Compass className="size-5 text-muted-foreground" aria-hidden="true" />
          Page not found
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          The page you are looking for does not exist or has moved.
        </p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Button asChild>
          <Link href="/">Back to home</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    </main>
  );
}

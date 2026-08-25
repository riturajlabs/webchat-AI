import Link from 'next/link';

import { Button } from '@/components/ui/button';

export function FinalCta() {
  return (
    <section>
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-5 px-4 py-16 text-center md:px-6 md:py-24">
        <h2 className="max-w-2xl text-balance font-sans text-3xl font-bold tracking-tight">
          Ready to give your website an AI assistant?
        </h2>
        <p className="max-w-xl text-balance text-muted-foreground">
          Create an account, add your first website, and embed the widget in minutes.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button asChild size="lg">
            <Link href="/signup">Get Started</Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href="/docs">Read the docs</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

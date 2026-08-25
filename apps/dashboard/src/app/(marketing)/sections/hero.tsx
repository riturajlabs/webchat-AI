import Link from 'next/link';

import { Button } from '@/components/ui/button';

export function Hero() {
  return (
    <section className="border-b">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-6 px-4 py-20 text-center md:px-6 md:py-28">
        <h1 className="max-w-3xl text-balance font-sans text-4xl font-bold tracking-tight md:text-5xl">
          Turn your website content into an AI assistant your visitors can talk to
        </h1>
        <p className="max-w-2xl text-balance text-base text-muted-foreground md:text-lg">
          WebChat AI crawls your website into a knowledge base and answers visitor questions with
          retrieval-augmented generation — grounded in your content, embedded with one script tag.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button asChild size="lg">
            <Link href="/signup">Create free account</Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href="/docs">Read the docs</Link>
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Add a website, embed one script tag — set up in minutes, no code required.
        </p>
      </div>
    </section>
  );
}

import Link from 'next/link';
import { Bot } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { MobileMenu } from './mobile-menu';

export const MARKETING_NAV_LINKS = [
  { href: '/#features', label: 'Features' },
  { href: '/docs', label: 'Docs' },
  { href: '/#pricing', label: 'Pricing' },
] as const;

export function BrandMark() {
  return (
    <Link href="/" className="flex items-center gap-2 font-semibold" aria-label="WebChat AI home">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-white shadow-sm">
        <Bot className="size-4" aria-hidden="true" />
      </span>
      WebChat AI
    </Link>
  );
}

export function Navbar() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <BrandMark />
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {MARKETING_NAV_LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <Button asChild variant="ghost">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button
            asChild
            className="bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600"
          >
            <Link href="/signup">Get Started</Link>
          </Button>
        </div>
        <MobileMenu />
      </div>
    </header>
  );
}

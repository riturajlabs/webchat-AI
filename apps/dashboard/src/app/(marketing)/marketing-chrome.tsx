import Link from 'next/link';
import { Bot } from 'lucide-react';

import { Button } from '@/components/ui/button';

const NAV_LINKS = [
  { href: '/#features', label: 'Features' },
  { href: '/docs', label: 'Docs' },
  { href: '/#pricing', label: 'Pricing' },
];

export function Navbar() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold"
          aria-label="WebChat AI home"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Bot className="size-4" aria-hidden="true" />
          </span>
          WebChat AI
        </Link>
        <nav
          aria-label="Marketing"
          className="hidden items-center gap-6 text-sm text-muted-foreground md:flex"
        >
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="transition-colors hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/signup">Get Started</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}

const FOOTER_GROUPS = [
  {
    title: 'Product',
    links: [
      { href: '/#features', label: 'Features' },
      { href: '/#how-it-works', label: 'How it works' },
      { href: '/#pricing', label: 'Pricing' },
      { href: '/docs', label: 'Documentation' },
    ],
  },
  {
    title: 'Company',
    links: [
      { href: '/signup', label: 'Get started' },
      { href: '/login', label: 'Sign in' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { href: '/privacy', label: 'Privacy' },
      { href: '/terms', label: 'Terms' },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t bg-muted/30">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-12 md:grid-cols-[2fr_1fr_1fr_1fr] md:px-6">
        <div className="flex flex-col gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold"
            aria-label="WebChat AI home"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Bot className="size-4" aria-hidden="true" />
            </span>
            WebChat AI
          </Link>
          <p className="max-w-xs text-sm text-muted-foreground">
            AI chat assistants grounded in your website content, powered by retrieval-augmented
            generation.
          </p>
        </div>
        {FOOTER_GROUPS.map((group) => (
          <nav key={group.title} aria-label={group.title} className="flex flex-col gap-3">
            <p className="text-sm font-semibold">{group.title}</p>
            {group.links.map((link) => (
              <Link
                key={link.href + link.label}
                href={link.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        ))}
      </div>
      <div className="border-t">
        <div className="mx-auto w-full max-w-6xl px-4 py-4 md:px-6">
          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} WebChat AI. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

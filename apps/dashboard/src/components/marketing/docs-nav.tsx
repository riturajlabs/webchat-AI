'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Button } from '@/components/ui/button';

const DOCS_NAV_ITEMS = [
  { href: '/docs', label: 'Overview' },
  { href: '/docs/quickstart', label: 'Quickstart' },
  { href: '/docs/embed', label: 'Embed' },
  { href: '/docs/configuration', label: 'Configuration' },
  { href: '/docs/api', label: 'API' },
  { href: '/docs/changelog', label: 'Changelog' },
] as const;

function isActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== '/docs' && pathname.startsWith(`${href}/`));
}

export function DocsSidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-20 hidden h-fit w-56 shrink-0 flex-col gap-1 lg:flex">
      <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Documentation
      </p>
      <nav aria-label="Documentation" className="flex flex-col gap-1">
        {DOCS_NAV_ITEMS.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            aria-current={isActive(pathname, href) ? 'page' : undefined}
            className={
              isActive(pathname, href)
                ? 'rounded-md bg-blue-600/10 px-3 py-2 text-sm font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-400'
                : 'rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'
            }
          >
            {label}
          </Link>
        ))}
      </nav>
      <div className="mt-6 rounded-lg border border-border/60 bg-muted/50 p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">Ready to launch?</p>
        <Button
          asChild
          size="sm"
          className="w-full bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-600"
        >
          <Link href="/signup">Get Started Free</Link>
        </Button>
      </div>
    </aside>
  );
}

export function DocsMobileNav() {
  const pathname = usePathname();

  return (
    <div className="border-b border-border/60 bg-background/80 backdrop-blur lg:hidden">
      <nav
        aria-label="Documentation"
        className="mx-auto flex w-full max-w-6xl items-center gap-1 overflow-x-auto px-4 py-2 sm:px-6"
      >
        {DOCS_NAV_ITEMS.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            aria-current={isActive(pathname, href) ? 'page' : undefined}
            className={
              isActive(pathname, href)
                ? 'whitespace-nowrap rounded-md bg-blue-600/10 px-3 py-1.5 text-sm font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-400'
                : 'whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'
            }
          >
            {label}
          </Link>
        ))}
        <Link
          href="/signup"
          className="ml-auto flex shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Get Started
        </Link>
      </nav>
    </div>
  );
}

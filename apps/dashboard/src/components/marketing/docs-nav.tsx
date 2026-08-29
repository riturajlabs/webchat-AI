'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { DOCS_NAV_GROUPS, isDocsActive } from '@/features/docs/docs-nav';
import { getLandingDestination } from '@/lib/landing-navigation';
import { cn } from '@/lib/utils';

function ActiveLink({
  href,
  label,
  pathname,
  className,
}: {
  href: string;
  label: string;
  pathname: string;
  className?: string;
}) {
  const active = isDocsActive(pathname, href);
  return (
    <Link
      href={href}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'block rounded-md px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
        className,
      )}
    >
      {label}
    </Link>
  );
}

function SidebarNav({ pathname }: { pathname: string }) {
  const [query, setQuery] = useState('');

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return DOCS_NAV_GROUPS;
    }
    return DOCS_NAV_GROUPS.map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          item.label.toLowerCase().includes(q) || item.description?.toLowerCase().includes(q),
      ),
    })).filter((group) => group.items.length > 0);
  }, [query]);

  return (
    <>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <label htmlFor="docs-search" className="sr-only">
          Search documentation
        </label>
        <input
          id="docs-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search docs…"
          className="h-9 w-full rounded-md border border-input bg-muted/40 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <nav aria-label="Documentation" className="flex flex-col gap-5">
        {groups.map((group) => (
          <div key={group.title} className="flex flex-col gap-1">
            <p className="px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {group.title}
            </p>
            {group.items.map((item) => (
              <ActiveLink key={item.href} href={item.href} label={item.label} pathname={pathname} />
            ))}
          </div>
        ))}
      </nav>
    </>
  );
}

export function DocsSidebar() {
  const pathname = usePathname();
  const { isAuthenticated, status } = useAuth();
  const isReady = status === 'ready';
  const ctaHref = getLandingDestination('get-started', isAuthenticated);
  const ctaLabel = isReady && isAuthenticated ? 'Open Dashboard' : 'Get Started Free';

  return (
    <aside className="sticky top-20 hidden h-fit w-60 shrink-0 flex-col gap-6 lg:flex">
      <SidebarNav pathname={pathname} />
      <div className="rounded-lg border border-border/60 bg-muted/50 p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {isReady && isAuthenticated ? 'Back to your workspace' : 'Ready to launch?'}
        </p>
        <Button
          asChild
          size="sm"
          className="w-full bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-600"
        >
          <Link href={ctaHref}>{ctaLabel}</Link>
        </Button>
      </div>
    </aside>
  );
}

export function DocsMobileNav() {
  const pathname = usePathname();
  const { isAuthenticated, status } = useAuth();
  const isReady = status === 'ready';
  const ctaHref = getLandingDestination('get-started', isAuthenticated);
  const ctaLabel = isReady && isAuthenticated ? 'Dashboard' : 'Get Started';

  return (
    <div className="sticky top-16 z-30 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 lg:hidden">
      <nav
        aria-label="Documentation"
        className="mx-auto flex w-full max-w-6xl items-center gap-1 overflow-x-auto px-4 py-2 sm:px-6"
      >
        {DOCS_NAV_GROUPS.flatMap((group) =>
          group.items.map((item) => (
            <ActiveLink
              key={item.href}
              href={item.href}
              label={item.label}
              pathname={pathname}
              className="whitespace-nowrap"
            />
          )),
        )}
        <Link
          href={ctaHref}
          className="ml-auto flex shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          {ctaLabel}
        </Link>
      </nav>
    </div>
  );
}

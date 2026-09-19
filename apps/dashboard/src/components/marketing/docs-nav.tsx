'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown, ChevronRight, Menu, Search, X } from 'lucide-react';
import { useEffect, useId, useMemo, useState } from 'react';

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
  onClick,
}: {
  href: string;
  label: string;
  pathname: string;
  className?: string;
  onClick?: () => void;
}) {
  const active = isDocsActive(pathname, href);
  return (
    <Link
      href={href}
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'block rounded-md pl-5 pr-3 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-blue-600/10 text-blue-700 font-semibold dark:bg-blue-500/15 dark:text-blue-400'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
        className,
      )}
    >
      {label}
    </Link>
  );
}

function DocsNavGroup({
  group,
  pathname,
  forceExpanded,
  onItemClick,
}: {
  group: (typeof DOCS_NAV_GROUPS)[number];
  pathname: string;
  forceExpanded?: boolean;
  onItemClick?: () => void;
}) {
  const groupId = useId();
  const hasActiveItem = group.items.some((item) => isDocsActive(pathname, item.href));
  const [expanded, setExpanded] = useState(true);
  const isExpanded = forceExpanded || expanded;

  useEffect(() => {
    if (hasActiveItem) {
      setExpanded(true);
    }
  }, [hasActiveItem]);

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        className="flex items-center gap-1.5 rounded-md px-2.5 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-expanded={isExpanded}
        aria-controls={groupId}
        onClick={() => setExpanded((previous) => !previous)}
      >
        {isExpanded ? (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronRight className="size-3.5" aria-hidden="true" />
        )}
        <span>{group.title}</span>
      </button>
      <div id={groupId} hidden={!isExpanded} className="flex flex-col gap-1">
        {group.items.map((item) => (
          <ActiveLink
            key={item.href}
            href={item.href}
            label={item.label}
            pathname={pathname}
            onClick={onItemClick}
          />
        ))}
      </div>
    </div>
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
          placeholder="Filter docs..."
          className="h-9 w-full rounded-md border border-input bg-muted/40 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <nav aria-label="Documentation" className="flex flex-col gap-5">
        {groups.map((group) => (
          <DocsNavGroup
            key={group.title}
            group={group}
            pathname={pathname}
            forceExpanded={Boolean(query)}
          />
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
    <aside className="sticky top-20 hidden h-fit w-64 shrink-0 flex-col gap-6 lg:flex">
      <SidebarNav pathname={pathname} />
      <div className="rounded-lg border border-border/60 bg-muted/40 p-3.5">
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

  const [isOpen, setIsOpen] = useState(false);
  const [mobileQuery, setMobileQuery] = useState('');

  const activeItem = DOCS_NAV_GROUPS.flatMap((g) => g.items).find((i) =>
    isDocsActive(pathname, i.href),
  );

  const filteredGroups = useMemo(() => {
    const q = mobileQuery.trim().toLowerCase();
    if (!q) return DOCS_NAV_GROUPS;
    return DOCS_NAV_GROUPS.map((g) => ({
      ...g,
      items: g.items.filter(
        (i) => i.label.toLowerCase().includes(q) || i.description?.toLowerCase().includes(q),
      ),
    })).filter((g) => g.items.length > 0);
  }, [mobileQuery]);

  return (
    <div className="sticky top-16 z-30 border-b border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:hidden">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-2 px-4 py-2 sm:px-6">
        <button
          type="button"
          onClick={() => setIsOpen((prev) => !prev)}
          className="flex items-center gap-2 rounded-md border border-input bg-muted/40 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
          aria-expanded={isOpen}
          aria-label="Toggle documentation navigation"
        >
          {isOpen ? (
            <X className="size-4" aria-hidden="true" />
          ) : (
            <Menu className="size-4" aria-hidden="true" />
          )}
          <span className="truncate max-w-[180px]">{activeItem?.label ?? 'Menu'}</span>
          <ChevronDown
            className={cn(
              'size-3.5 text-muted-foreground transition-transform',
              isOpen && 'rotate-180',
            )}
            aria-hidden="true"
          />
        </button>

        <Link
          href={ctaHref}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        >
          {ctaLabel}
        </Link>
      </div>

      {isOpen ? (
        <div className="border-t border-border/60 bg-background px-4 py-4 shadow-lg sm:px-6">
          <div className="relative mb-4">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              type="search"
              value={mobileQuery}
              onChange={(e) => setMobileQuery(e.target.value)}
              placeholder="Search docs..."
              className="h-9 w-full rounded-md border border-input bg-muted/40 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          <nav
            aria-label="Mobile Documentation Navigation"
            className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto pr-1"
          >
            {filteredGroups.map((group) => (
              <DocsNavGroup
                key={group.title}
                group={group}
                pathname={pathname}
                forceExpanded={Boolean(mobileQuery)}
                onItemClick={() => setIsOpen(false)}
              />
            ))}
          </nav>
        </div>
      ) : null}
    </div>
  );
}

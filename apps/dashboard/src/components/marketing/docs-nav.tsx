'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

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
      </nav>
    </div>
  );
}

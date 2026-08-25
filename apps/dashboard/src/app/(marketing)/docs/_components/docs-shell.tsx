import Link from 'next/link';
import type { ReactNode } from 'react';

const DOC_NAV = [
  { href: '/docs', label: 'Overview' },
  { href: '/docs/quickstart', label: 'Quickstart' },
  { href: '/docs/embed', label: 'Embed' },
  { href: '/docs/configuration', label: 'Configuration' },
  { href: '/docs/api', label: 'API' },
  { href: '/docs/changelog', label: 'Changelog' },
];

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      aria-current={active ? 'page' : undefined}
      className={
        active
          ? 'rounded-md bg-muted px-3 py-1.5 text-sm font-medium text-foreground'
          : 'rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground'
      }
    >
      {label}
    </Link>
  );
}

/**
 * Shared layout for the public developer docs: section navigation plus the
 * page body. Rendered per page (instead of reading the pathname) so it stays
 * a pure server component with zero client JavaScript.
 */
export function DocsShell({ active, children }: { active: string; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 md:px-6 md:py-14 lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:gap-12">
      <nav aria-label="Documentation" className="mb-8 lg:mb-0">
        <p className="mb-2 hidden px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground lg:block">
          Documentation
        </p>
        <div className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
          {DOC_NAV.map((item) => (
            <NavLink key={item.href} {...item} active={active === item.href} />
          ))}
        </div>
      </nav>
      <article className="flex min-w-0 flex-col gap-6">{children}</article>
    </div>
  );
}

/** Section wrapper matching the dashboard docs Card pattern. */
export function DocSection({
  id,
  title,
  description,
  children,
}: {
  id?: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20 rounded-lg border bg-background p-5">
      <h2 className="font-sans text-lg font-semibold tracking-tight">{title}</h2>
      {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      <div className="mt-4 flex flex-col gap-4">{children}</div>
    </section>
  );
}

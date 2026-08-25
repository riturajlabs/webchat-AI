'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { visibleNavGroups, isNavActive } from '@/components/layout/nav-items';
import { cn } from '@/lib/utils';

/**
 * Grouped nav links shared by the desktop sidebar and the mobile drawer so
 * grouping, labels, and active states stay identical across breakpoints.
 */
export function NavLinks({
  role,
  onNavigate,
  className,
}: {
  role: string | undefined;
  onNavigate?: () => void;
  className?: string;
}) {
  const pathname = usePathname();

  return (
    <div className={cn('flex flex-col', className)}>
      {visibleNavGroups(role).map((group) => (
        <div key={group.label} className="flex flex-col">
          <p className="px-3 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground first:pt-1">
            {group.label}
          </p>
          <div className="flex flex-col gap-0.5">
            {group.items.map(({ href, label, icon: Icon }) => {
              const active = isNavActive(pathname, href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? 'page' : undefined}
                  onClick={onNavigate}
                  className={cn(
                    'flex items-center gap-3 rounded-md px-3 py-3 text-sm transition-colors',
                    active
                      ? 'border-l-2 border-primary bg-primary/10 font-medium text-primary'
                      : 'border-l-2 border-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  )}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

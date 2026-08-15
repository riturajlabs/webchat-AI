'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BarChart3, Building2, Gauge, ScrollText, Server, Users } from 'lucide-react';

import { cn } from '@/lib/utils';

const ADMIN_NAV_ITEMS = [
  { href: '/admin/overview', label: 'Overview', icon: Gauge },
  { href: '/admin/tenants', label: 'Tenants', icon: Building2 },
  { href: '/admin/users', label: 'Users', icon: Users },
  { href: '/admin/revenue', label: 'Revenue', icon: BarChart3 },
  { href: '/admin/system', label: 'System', icon: Server },
  { href: '/admin/audit', label: 'Audit', icon: ScrollText },
  { href: '/admin/crawl-jobs', label: 'Crawl queue', icon: Server },
];

/** Secondary navigation for the SaaS operations panel (Phase 15). */
export function AdminNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Admin sections" className="flex flex-wrap items-center gap-1 border-b pb-px">
      {ADMIN_NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
              active && 'bg-muted text-foreground',
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

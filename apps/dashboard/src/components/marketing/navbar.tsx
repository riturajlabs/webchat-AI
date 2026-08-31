'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Bot, ChevronDown, LayoutDashboard, LogOut } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { getLandingDestination } from '@/lib/landing-navigation';
import { cn } from '@/lib/utils';

import { MobileMenu } from './mobile-menu';

export const MARKETING_NAV_LINKS = [
  { href: '/', label: 'Home' },
  { href: '/features', label: 'Features' },
  { href: '/how-it-works', label: 'How it works' },
  { href: '/integrations', label: 'Integrations' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/docs', label: 'Docs' },
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

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '?';
  }
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase();
}

function UserMenu({ onLogout, isLoggingOut }: { onLogout: () => void; isLoggingOut: boolean }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        close();
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        close();
      }
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);

  return (
    <div ref={menuRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-md px-1 py-1 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
          {initials(user?.name ?? '?')}
        </span>
        <ChevronDown
          className={cn('size-4 text-muted-foreground transition-transform', open && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full mt-2 w-56 overflow-hidden rounded-lg border border-border/60 bg-background shadow-lg"
        >
          <div className="border-b border-border/60 px-4 py-3">
            <p className="truncate text-sm font-medium">{user?.name}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
          </div>
          <Link
            href="/dashboard"
            role="menuitem"
            onClick={close}
            className="flex items-center gap-2 px-4 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <LayoutDashboard className="size-4" aria-hidden="true" />
            Dashboard
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={onLogout}
            disabled={isLoggingOut}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            <LogOut className="size-4" aria-hidden="true" />
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function Navbar() {
  const { isAuthenticated, status, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const isReady = status === 'ready';

  async function handleLogout() {
    if (isLoggingOut) {
      return;
    }
    setIsLoggingOut(true);
    try {
      await logout();
      router.push('/');
    } finally {
      setIsLoggingOut(false);
    }
  }

  const signInHref = getLandingDestination('sign-in', isAuthenticated);
  const getStartedHref = getLandingDestination('get-started', isAuthenticated);

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <BrandMark />
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {MARKETING_NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  'rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-foreground',
                  active ? 'text-foreground' : 'text-muted-foreground',
                )}
              >
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="flex shrink-0 items-center gap-1.5">
          {isReady ? (
            isAuthenticated ? (
              <UserMenu onLogout={() => void handleLogout()} isLoggingOut={isLoggingOut} />
            ) : (
              <>
                <Button asChild variant="ghost">
                  <Link href={signInHref}>Sign in</Link>
                </Button>
                <Button
                  asChild
                  className="hidden bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600 sm:inline-flex"
                >
                  <Link href={getStartedHref}>Get Started</Link>
                </Button>
              </>
            )
          ) : (
            <span
              className="hidden h-9 w-24 animate-pulse rounded-md bg-muted sm:block"
              aria-hidden="true"
            />
          )}
          <MobileMenu />
        </div>
      </div>
    </header>
  );
}

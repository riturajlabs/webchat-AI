'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { LayoutDashboard, LogOut, Menu, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { getLandingDestination } from '@/lib/landing-navigation';

import { MARKETING_NAV_LINKS } from './navbar';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '?';
  }
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase();
}

export function MobileMenu() {
  const { isAuthenticated, status, user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const isReady = status === 'ready';

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  async function handleLogout() {
    if (isLoggingOut) {
      return;
    }
    setIsLoggingOut(true);
    try {
      close();
      await logout();
      router.push('/');
    } finally {
      setIsLoggingOut(false);
    }
  }

  useEffect(() => {
    if (!open) {
      return;
    }
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        close();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  const signInHref = getLandingDestination('sign-in', isAuthenticated);
  const getStartedHref = getLandingDestination('get-started', isAuthenticated);

  return (
    <div className="md:hidden">
      <button
        ref={triggerRef}
        type="button"
        aria-label="Menu"
        aria-expanded={open}
        aria-controls="marketing-mobile-menu"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-input bg-background shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {open ? (
          <X className="size-5" aria-hidden="true" />
        ) : (
          <Menu className="size-5" aria-hidden="true" />
        )}
      </button>
      {open ? (
        <div
          id="marketing-mobile-menu"
          className="fixed inset-x-0 top-16 z-40 border-b bg-background shadow-lg"
        >
          <nav
            aria-label="Mobile"
            className="mx-auto flex max-w-6xl flex-col gap-1 overflow-y-auto px-4 py-4 sm:px-6"
          >
            <div className="px-3 pb-2">
              <p className="font-semibold">WebChat AI</p>
            </div>
            {MARKETING_NAV_LINKS.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                onClick={close}
                className="rounded-md px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {label}
              </Link>
            ))}
            <div className="my-2 border-t" />
            {isReady ? (
              isAuthenticated ? (
                <>
                  <div className="flex items-center gap-3 px-3 py-2">
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">
                      {initials(user?.name ?? '?')}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{user?.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
                    </div>
                  </div>
                  <Button asChild variant="default" className="justify-start">
                    <Link href="/dashboard" onClick={close}>
                      <LayoutDashboard className="size-4" aria-hidden="true" />
                      Dashboard
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    className="justify-start"
                    onClick={() => void handleLogout()}
                    disabled={isLoggingOut}
                  >
                    <LogOut className="size-4" aria-hidden="true" />
                    {isLoggingOut ? 'Signing out…' : 'Sign out'}
                  </Button>
                </>
              ) : (
                <>
                  <Button asChild variant="outline" className="justify-start">
                    <Link href={signInHref} onClick={close}>
                      Sign in
                    </Link>
                  </Button>
                  <Button
                    asChild
                    className="justify-start bg-blue-600 text-white hover:bg-blue-700"
                  >
                    <Link href={getStartedHref} onClick={close}>
                      Get Started
                    </Link>
                  </Button>
                </>
              )
            ) : null}
          </nav>
        </div>
      ) : null}
    </div>
  );
}

'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Bot, Menu, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { NavLinks } from '@/components/layout/nav-links';

export function MobileNav() {
  const pathname = usePathname();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) {
      return;
    }
    // Lock body scroll while the drawer is open.
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panelRef.current?.focus();
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

  // Close the drawer after client-side navigation completes.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <>
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon"
        className="h-11 w-11 md:hidden"
        aria-label="Open navigation"
        aria-expanded={open}
        aria-controls="mobile-nav"
        onClick={() => setOpen((value) => !value)}
      >
        <Menu className="size-5" aria-hidden="true" />
      </Button>

      {open ? (
        <div id="mobile-nav" className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/50" aria-hidden="true" onClick={close} />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 flex w-64 max-w-[85vw] flex-col border-r bg-background shadow-lg outline-none"
          >
            <div className="flex items-center justify-between gap-2 px-5 py-5">
              <Link
                href="/dashboard"
                className="flex items-center gap-2 font-semibold"
                onClick={close}
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
                  <Bot className="size-4" aria-hidden="true" />
                </span>
                WebChat AI
              </Link>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11"
                aria-label="Close navigation"
                onClick={close}
              >
                <X className="size-5" aria-hidden="true" />
              </Button>
            </div>

            <nav className="flex-1 px-3 pb-4" aria-label="Mobile navigation">
              <NavLinks role={user?.role} onNavigate={close} />
            </nav>
          </div>
        </div>
      ) : null}
    </>
  );
}

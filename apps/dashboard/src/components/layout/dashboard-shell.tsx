'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Bot, LogOut } from 'lucide-react';
import { useState } from 'react';

import { useAuth } from '@/features/auth/auth-context';
import { VerificationReminder } from '@/features/auth/verification-reminder';
import { Button } from '@/components/ui/button';
import { CrawlStatusBanner } from '@/components/layout/crawl-status-banner';
import { MobileNav } from '@/components/layout/mobile-nav';
import { NavLinks } from '@/components/layout/nav-links';
import { ThemeToggle } from '@/components/theme/theme-toggle';

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    if (isLoggingOut) {
      return;
    }
    setIsLoggingOut(true);
    try {
      await logout();
      router.push('/login');
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-muted/30">
      <aside className="hidden w-60 shrink-0 flex-col overflow-y-auto border-r bg-background md:flex">
        <Link href="/dashboard" className="flex items-center gap-2 px-5 py-5 font-semibold">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Bot className="size-4" aria-hidden="true" />
          </span>
          WebChat AI
        </Link>
        <nav className="flex-1 px-3 pb-4" aria-label="Main navigation">
          <NavLinks role={user?.role} />
        </nav>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="sticky top-0 z-10 flex shrink-0 items-center justify-between gap-4 border-b bg-background px-4 py-3 md:px-10">
          <div className="flex min-w-0 items-center gap-2">
            <MobileNav />
            <p className="truncate text-sm text-muted-foreground">
              Welcome{user ? `, ${user.name}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <span className="hidden text-sm text-muted-foreground sm:inline">{user?.email}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleLogout()}
              disabled={isLoggingOut}
            >
              <LogOut className="size-4" aria-hidden="true" />
              {isLoggingOut ? 'Signing out…' : 'Sign out'}
            </Button>
          </div>
        </header>
        <VerificationReminder />
        <CrawlStatusBanner />
        <div className="flex-1 overflow-y-auto px-4 py-8 md:px-10">{children}</div>
      </main>
    </div>
  );
}

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowLeft, ArrowRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { getPrevNext } from '@/features/docs/docs-nav';
import { getLandingDestination } from '@/lib/landing-navigation';

export function DocsFooter() {
  const pathname = usePathname();
  const { isAuthenticated, status } = useAuth();
  const isReady = status === 'ready';
  const ctaHref = getLandingDestination('get-started', isAuthenticated);
  const ctaLabel = isReady && isAuthenticated ? 'Open Dashboard' : 'Get Started Free';
  const { prev, next } = getPrevNext(pathname);

  return (
    <div className="mt-12 flex flex-col gap-8">
      {prev || next ? (
        <nav
          aria-label="Pagination"
          className="grid gap-4 border-t border-border/60 pt-8 sm:grid-cols-2"
        >
          {prev ? (
            <Link
              href={prev.href}
              className="group flex flex-col gap-1 rounded-lg border border-border/60 p-4 transition-colors hover:border-blue-600/40 hover:bg-muted/40"
            >
              <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <ArrowLeft className="size-3.5" aria-hidden="true" /> Previous
              </span>
              <span className="text-sm font-medium">{prev.label}</span>
            </Link>
          ) : (
            <span />
          )}
          {next ? (
            <Link
              href={next.href}
              className="group flex flex-col items-end gap-1 rounded-lg border border-border/60 p-4 text-right transition-colors hover:border-blue-600/40 hover:bg-muted/40 sm:col-start-2"
            >
              <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Next <ArrowRight className="size-3.5" aria-hidden="true" />
              </span>
              <span className="text-sm font-medium">{next.label}</span>
            </Link>
          ) : (
            <span />
          )}
        </nav>
      ) : null}

      <div className="border-t border-border/60 bg-muted/30 px-4 py-6">
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="max-w-sm">
            <p className="text-sm font-medium text-foreground">Ready to build?</p>
            <p className="text-sm text-muted-foreground">
              Register a website and get a live assistant in minutes.
            </p>
          </div>
          <Button
            asChild
            className="bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-600"
          >
            <Link href={ctaHref}>{ctaLabel}</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

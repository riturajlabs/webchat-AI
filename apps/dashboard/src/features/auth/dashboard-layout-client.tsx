'use client';

import { AuthGuard } from '@/features/auth/auth-guard';
import { DashboardShell } from '@/components/layout/dashboard-shell';
import { CrawlActivityProvider } from '@/features/websites/crawl-activity-context';

export function DashboardLayoutClient({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <CrawlActivityProvider>
        <DashboardShell>{children}</DashboardShell>
      </CrawlActivityProvider>
    </AuthGuard>
  );
}

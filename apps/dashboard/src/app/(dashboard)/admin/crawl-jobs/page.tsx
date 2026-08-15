import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { AdminNav } from '@/features/admin/admin-nav';
import { CrawlPanel } from '@/features/admin/crawl-panel';

export const metadata: Metadata = {
  title: 'Admin Crawl Queue',
};

export default function AdminCrawlQueueRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Crawl queue</h1>
          <p className="text-sm text-muted-foreground">Knowledge base crawl jobs across tenants.</p>
        </div>
        <AdminNav />
        <CrawlPanel />
      </div>
    </AdminGuard>
  );
}

import type { Metadata } from 'next';

import { AdminGuard } from '@/features/admin/admin-guard';
import { PageHeader } from '@/components/ui/page-header';
import { AdminNav } from '@/features/admin/admin-nav';
import { CrawlPanel } from '@/features/admin/crawl-panel';

export const metadata: Metadata = {
  title: 'Admin Crawl Queue',
};

export default function AdminCrawlQueueRoute() {
  return (
    <AdminGuard>
      <div className="flex flex-col gap-6">
        <PageHeader title="Crawl queue" description="Knowledge base crawl jobs across tenants." />
        <AdminNav />
        <CrawlPanel />
      </div>
    </AdminGuard>
  );
}

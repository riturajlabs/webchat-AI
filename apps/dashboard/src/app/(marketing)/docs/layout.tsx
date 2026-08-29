import { DocsMobileNav, DocsSidebar } from '@/components/marketing/docs-nav';
import { DocsOnThisPage } from '@/features/docs/docs-client';
import { DocsFooter } from '@/features/docs/docs-footer';

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <DocsMobileNav />
      <div className="mx-auto flex w-full max-w-7xl gap-10 px-4 py-10 sm:px-6 lg:py-14">
        <DocsSidebar />
        <main id="docs-content" className="min-w-0 max-w-3xl flex-1">
          {children}
          <DocsFooter />
        </main>
        <DocsOnThisPage />
      </div>
    </div>
  );
}

import Link from 'next/link';

import { DocsMobileNav, DocsSidebar } from '@/components/marketing/docs-nav';

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <DocsMobileNav />
      <div className="mx-auto flex w-full max-w-6xl gap-10 px-4 py-10 sm:px-6 lg:py-14">
        <DocsSidebar />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
      <div className="border-t border-border/60 bg-muted/30">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 text-sm text-muted-foreground sm:px-6">
          <p>WebChat AI Developer Documentation</p>
          <Link
            href="/signup"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Get Started
          </Link>
        </div>
      </div>
    </div>
  );
}

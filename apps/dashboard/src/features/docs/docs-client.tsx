'use client';

import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

interface TabItem {
  label: string;
  value: string;
  content: React.ReactNode;
}

/**
 * Lightweight tabs for the docs. No external dependency; keeps panel state
 * local so each tab group is independent and keyboard-accessible.
 */
export function Tabs({ tabs, defaultValue }: { tabs: TabItem[]; defaultValue?: string }) {
  const first = defaultValue ?? tabs[0]?.value ?? '';
  const [active, setActive] = useState(first);

  return (
    <div>
      <div
        role="tablist"
        aria-label="Tabs"
        className="inline-flex gap-1 rounded-lg border border-input bg-muted/50 p-1"
      >
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active === tab.value}
            onClick={() => setActive(tab.value)}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
              active === tab.value
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div key={tab.value} role="tabpanel" hidden={active !== tab.value} className="mt-4">
          {tab.content}
        </div>
      ))}
    </div>
  );
}

interface TocItem {
  id: string;
  label: string;
}

function collectHeadings(root: HTMLElement): TocItem[] {
  const items: TocItem[] = [];
  root.querySelectorAll('h2[id]').forEach((node) => {
    const id = node.getAttribute('id');
    const label = node.textContent?.trim();
    if (id && label) {
      items.push({ id, label });
    }
  });
  return items;
}

/**
 * "On this page" table of contents. Reads section headings (h2 with an id)
 * from the main content, highlights the one in view, and links to the anchors.
 * Falls back to the section ids the page declares.
 */
export function DocsOnThisPage({ sections = [] }: { sections?: TocItem[] }) {
  const [items, setItems] = useState<TocItem[]>(() => (sections.length ? sections : []));
  const [activeId, setActiveId] = useState<string | null>(sections.length ? sections[0]!.id : null);

  useEffect(() => {
    const root = document.getElementById('docs-content');
    const found = root ? collectHeadings(root) : [];
    if (found.length) {
      setItems(found);
      setActiveId(found[0]?.id ?? null);
    }

    if (!found.length) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: '-96px 0px -60% 0px', threshold: 0 },
    );

    for (const item of found) {
      const node = document.getElementById(item.id);
      if (node) {
        observer.observe(node);
      }
    }

    return () => observer.disconnect();
  }, []);

  if (items.length === 0) {
    return null;
  }

  return (
    <div className="sticky top-24 hidden w-56 shrink-0 flex-col gap-4 self-start xl:block">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        On this page
      </p>
      <nav aria-label="On this page" className="flex flex-col gap-1 text-sm">
        {items.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className={cn(
              'border-l pl-3 text-muted-foreground transition-colors hover:text-foreground',
              activeId === item.id
                ? 'border-blue-600 font-medium text-foreground'
                : 'border-border',
            )}
          >
            {item.label}
          </a>
        ))}
      </nav>
    </div>
  );
}

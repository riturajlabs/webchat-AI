'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

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
  level?: number;
}

function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .trim()
      .replace(/\s+/g, '-') || 'section'
  );
}

export function collectHeadings(root: HTMLElement): TocItem[] {
  const items: TocItem[] = [];
  const usedIds = new Set<string>();
  const slugCounts = new Map<string, number>();

  const headingNodes = root.querySelectorAll<HTMLElement>('h2, h3');
  headingNodes.forEach((node) => {
    // Exclude headings in hidden containers or breadcrumbs/headers
    if (node.closest('[hidden]') || node.closest('[aria-hidden="true"]')) {
      return;
    }

    const label = node.textContent?.trim();
    if (!label) {
      return;
    }

    const existingId = node.getAttribute('id');
    let id = existingId;
    if (!id || usedIds.has(id)) {
      // Check if parent section has an id
      const sectionId = node.closest('section[id]')?.getAttribute('id');
      if (sectionId && !usedIds.has(sectionId)) {
        id = sectionId;
      } else {
        const baseSlug = slugify(label);
        const count = slugCounts.get(baseSlug) ?? 0;
        id = count === 0 ? baseSlug : `${baseSlug}-${count}`;
        while (usedIds.has(id)) {
          const nextCount = (slugCounts.get(baseSlug) ?? count) + 1;
          slugCounts.set(baseSlug, nextCount);
          id = `${baseSlug}-${nextCount}`;
        }
        slugCounts.set(baseSlug, (slugCounts.get(baseSlug) ?? count) + 1);
      }
      node.setAttribute('id', id);
    }
    usedIds.add(id);

    // Ensure scroll margin so sticky header does not obscure heading
    if (!node.classList.contains('scroll-mt-24')) {
      node.classList.add('scroll-mt-24');
    }

    const level = node.tagName.toLowerCase() === 'h3' ? 3 : 2;
    if (!items.some((item) => item.id === id)) {
      items.push({ id, label, level });
    }
  });

  return items;
}

/**
 * "On this page" table of contents. Reads section headings (h2 and h3)
 * from the main content, highlights the one in view, and links to the anchors.
 * Falls back to the section ids the page declares.
 */
const DEFAULT_SECTIONS: TocItem[] = [];

export function DocsOnThisPage({ sections = DEFAULT_SECTIONS }: { sections?: TocItem[] }) {
  const pathname = usePathname();
  const [items, setItems] = useState<TocItem[]>(() => (sections.length ? sections : []));
  const [activeId, setActiveId] = useState<string | null>(sections.length ? sections[0]!.id : null);

  useEffect(() => {
    let unmounted = false;

    const syncHeadings = () => {
      const root = document.getElementById('docs-content');
      const found = root ? collectHeadings(root) : [];
      if (unmounted) return;

      if (found.length) {
        setItems(found);

        // Check if there is an initial hash in the URL
        const hash = typeof window !== 'undefined' ? window.location.hash.replace(/^#/, '') : '';
        if (hash && found.some((item) => item.id === hash)) {
          setActiveId(hash);
          const target = document.getElementById(hash);
          if (target) {
            const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            target.scrollIntoView({
              behavior: prefersReduced ? 'auto' : 'smooth',
              block: 'start',
            });
          }
        } else {
          setActiveId(found[0]?.id ?? null);
        }
      } else if (sections.length) {
        setItems(sections);
        setActiveId(sections[0]?.id ?? null);
      } else {
        setItems([]);
        setActiveId(null);
      }
    };

    // Sync immediately and schedule a frame for route transitions
    syncHeadings();
    const timer = setTimeout(syncHeadings, 50);

    return () => {
      unmounted = true;
      clearTimeout(timer);
    };
  }, [pathname, sections]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') {
      return;
    }
    if (!items.length) {
      return;
    }

    const visibleHeadings = new Set<string>();

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            visibleHeadings.add(entry.target.id);
          } else {
            visibleHeadings.delete(entry.target.id);
          }
        }

        // Active heading is the first visible heading from top to bottom
        const firstVisible = items.find((item) => visibleHeadings.has(item.id));
        if (firstVisible) {
          setActiveId(firstVisible.id);
        }
      },
      { rootMargin: '-96px 0px -60% 0px', threshold: [0, 1] },
    );

    for (const item of items) {
      const node = document.getElementById(item.id);
      if (node) {
        observer.observe(node);
      }
    }

    return () => observer.disconnect();
  }, [items]);

  const handleLinkClick = (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    const target = document.getElementById(id);
    if (target) {
      const prefersReduced =
        typeof window !== 'undefined' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      target.scrollIntoView({
        behavior: prefersReduced ? 'auto' : 'smooth',
        block: 'start',
      });
      window.history.pushState(null, '', `#${id}`);
      setActiveId(id);
      target.focus({ preventScroll: true });
    }
  };

  if (items.length === 0) {
    return null;
  }

  return (
    <div className="sticky top-24 hidden w-56 shrink-0 flex-col gap-3 self-start xl:flex">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        On this page
      </p>
      <nav aria-label="On this page" className="flex flex-col gap-1 text-sm">
        {items.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            onClick={(e) => handleLinkClick(e, item.id)}
            className={cn(
              'border-l transition-colors hover:text-foreground',
              item.level === 3
                ? 'pl-5 text-xs text-muted-foreground/80'
                : 'pl-3 text-sm text-muted-foreground',
              activeId === item.id
                ? 'border-blue-600 font-medium text-blue-600 dark:border-blue-400 dark:text-blue-400'
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

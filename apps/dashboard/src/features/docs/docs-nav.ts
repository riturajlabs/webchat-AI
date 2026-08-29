/**
 * Shared documentation navigation (information architecture).
 *
 * Plain data module — safe to import from both server and client components.
 * Used by the sidebar (client), the mobile nav (client), the on-this-page
 * layout and the prev/next footer (server). Keeps the IA in one place.
 */

export interface DocsNavItem {
  href: string;
  label: string;
  description?: string;
}

export interface DocsNavGroup {
  title: string;
  items: DocsNavItem[];
}

export const DOCS_NAV_GROUPS: DocsNavGroup[] = [
  {
    title: 'Getting started',
    items: [
      { href: '/docs', label: 'Overview', description: 'Platform and documentation map.' },
      {
        href: '/docs/quickstart',
        label: 'Quickstart',
        description: 'Install the widget on your site in minutes.',
      },
    ],
  },
  {
    title: 'Customization',
    items: [
      {
        href: '/docs/configuration',
        label: 'Configuration',
        description: 'Every widget option and the values it accepts.',
      },
      {
        href: '/docs/embed',
        label: 'Embed',
        description: 'Script tag, SDK init()/mount(), allowlists and CSP.',
      },
    ],
  },
  {
    title: 'Platform',
    items: [
      {
        href: '/docs/api',
        label: 'API reference',
        description: 'The REST endpoints behind the dashboard and widget.',
      },
      {
        href: '/docs/changelog',
        label: 'Changelog',
        description: 'Notable documentation and integration changes.',
      },
    ],
  },
];

export const DOCS_NAV_ITEMS: DocsNavItem[] = DOCS_NAV_GROUPS.flatMap((group) => group.items);

/** Previous/next ordering across the whole documentation tree. */
export const DOCS_ORDER: string[] = DOCS_NAV_ITEMS.map((item) => item.href);

export function findDocItem(href: string): DocsNavItem | undefined {
  return DOCS_NAV_ITEMS.find((item) => item.href === href);
}

export function getPrevNext(href: string): { prev?: DocsNavItem; next?: DocsNavItem } {
  const index = DOCS_ORDER.indexOf(href);
  if (index === -1) {
    return {};
  }
  return {
    prev: index > 0 ? DOCS_NAV_ITEMS[index - 1] : undefined,
    next: index < DOCS_NAV_ITEMS.length - 1 ? DOCS_NAV_ITEMS[index + 1] : undefined,
  };
}

/** True when `pathname` is exactly `href` or a descendant of it. */
export function isDocsActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== '/docs' && pathname.startsWith(`${href}/`));
}

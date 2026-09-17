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
        description: 'Go from content to a live assistant in 7 steps.',
      },
    ],
  },
  {
    title: 'Knowledge',
    items: [
      {
        href: '/docs/knowledge-sources',
        label: 'Knowledge sources',
        description: 'Websites, uploaded documents, and mixed ingestion modes.',
      },
      {
        href: '/docs/document-upload',
        label: 'File uploads',
        description: 'Supported formats (.pdf, .docx, .md, .txt), bounds, and processing.',
      },
      {
        href: '/docs/rag-pipeline',
        label: 'RAG & grounding',
        description: 'Hybrid search, reciprocal rank fusion, confidence scoring, and fallback.',
      },
    ],
  },
  {
    title: 'Widget',
    items: [
      {
        href: '/docs/embed',
        label: 'Embed',
        description: 'Hosted script tag, SDK init()/mount(), and CSP setup.',
      },
      {
        href: '/docs/customization',
        label: 'Customization',
        description: '11 theme presets, 10 curated fonts, bot branding, and layout.',
      },
      {
        href: '/docs/configuration',
        label: 'Configuration',
        description: 'Complete widget option reference and validation bounds.',
      },
      {
        href: '/docs/testing',
        label: 'Testing',
        description: 'Staging verification using the dashboard Widget Test page.',
      },
    ],
  },
  {
    title: 'Manage',
    items: [
      {
        href: '/docs/conversations',
        label: 'Conversations',
        description: 'Visitor chat logs, message transcripts, sources, and latency.',
      },
      {
        href: '/docs/analytics',
        label: 'Analytics & usage',
        description: 'Chat volume, top questions, response times, and monthly quotas.',
      },
    ],
  },
  {
    title: 'Developer',
    items: [
      {
        href: '/docs/api',
        label: 'API reference',
        description: 'REST endpoints, request/response payloads, and error codes.',
      },
      {
        href: '/docs/security',
        label: 'Security',
        description: 'Domain allowlists, origin validation, tenant isolation, and SSRF guard.',
      },
      {
        href: '/docs/troubleshooting',
        label: 'Troubleshooting',
        description: 'Verified failure modes, error codes, and step-by-step solutions.',
      },
    ],
  },
  {
    title: 'Reference',
    items: [
      {
        href: '/docs/changelog',
        label: 'Changelog',
        description: 'Notable documentation and integration surface changes.',
      },
    ],
  },
];

export const DOCS_NAV_ITEMS: DocsNavItem[] = DOCS_NAV_GROUPS.flatMap((group) => group.items);

/** Previous/next ordering following the logical learning path. */
export const DOCS_ORDER: string[] = [
  '/docs',
  '/docs/quickstart',
  '/docs/knowledge-sources',
  '/docs/document-upload',
  '/docs/rag-pipeline',
  '/docs/customization',
  '/docs/configuration',
  '/docs/testing',
  '/docs/embed',
  '/docs/conversations',
  '/docs/analytics',
  '/docs/api',
  '/docs/security',
  '/docs/troubleshooting',
  '/docs/changelog',
];

export function findDocItem(href: string): DocsNavItem | undefined {
  return DOCS_NAV_ITEMS.find((item) => item.href === href);
}

export function getPrevNext(href: string): { prev?: DocsNavItem; next?: DocsNavItem } {
  const index = DOCS_ORDER.indexOf(href);
  if (index === -1) {
    return {};
  }
  const prevHref = index > 0 ? DOCS_ORDER[index - 1] : undefined;
  const nextHref = index < DOCS_ORDER.length - 1 ? DOCS_ORDER[index + 1] : undefined;

  return {
    prev: prevHref ? findDocItem(prevHref) : undefined,
    next: nextHref ? findDocItem(nextHref) : undefined,
  };
}

/** True when `pathname` is exactly `href` or a descendant of it. */
export function isDocsActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== '/docs' && pathname.startsWith(`${href}/`));
}

import { Bullets, DocHeader, DocSection } from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/changelog',
  title: 'Changelog',
  description:
    'Notable changes to WebChat AI documentation and developer-facing integration surfaces.',
});

const ENTRIES = [
  {
    date: 'August 2026',
    version: 'Docs v1',
    items: [
      'Developer documentation restructured into Quickstart, Embed, Configuration, API and Changelog.',
      'Embed examples generated from the same builders the dashboard widget builder uses.',
      'API reference now mirrors the endpoints consumed by the dashboard.',
    ],
  },
];

export default function ChangelogPage() {
  return (
    <div className="flex flex-col gap-8">
      <DocHeader
        breadcrumb="Platform / Changelog"
        title="Changelog"
        lede="Notable changes to the documentation and developer-facing surfaces. New entries are appended at the top."
      />

      {ENTRIES.map((entry) => (
        <DocSection key={entry.version} title={entry.version} description={entry.date}>
          <Bullets items={entry.items} />
        </DocSection>
      ))}

      <DocSection
        id="format"
        title="Format"
        description="How entries in this changelog are structured."
      >
        <Bullets
          items={[
            'Each release lists documentation structure and integration-affecting changes.',
            'Product feature announcements live outside this document.',
          ]}
        />
      </DocSection>
    </div>
  );
}

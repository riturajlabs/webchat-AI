import type { Metadata } from 'next';
import Link from 'next/link';

import { CONFIG_OPTIONS, DASHBOARD_URL } from '@/features/docs/content';

import { DocsShell, DocSection } from '../_components/docs-shell';

export const metadata: Metadata = {
  title: 'Configuration',
  description:
    'Every WebChat AI widget option: themes, colors, welcome message, suggested questions and domain allowlist.',
};

export default function ConfigurationPage() {
  return (
    <DocsShell active="/docs/configuration">
      <header className="flex flex-col gap-3">
        <h1 className="font-sans text-3xl font-bold tracking-tight">Configuration</h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          Every field is editable from the dashboard widget builder (
          <code className="font-mono text-xs">PATCH /api/websites/{'{id}'}/widget</code>) — updates
          go live without touching your embed script.
        </p>
      </header>

      <DocSection
        title="Widget options"
        description="Appearance, behavior and security fields for each website's widget."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Option</th>
                <th className="py-1.5 pr-3 font-medium">Values</th>
                <th className="py-1.5 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {CONFIG_OPTIONS.map(({ key, values, description }) => (
                <tr key={key} className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-xs">{key}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-muted-foreground">{values}</td>
                  <td className="py-1.5 text-muted-foreground">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection
        title="Editing from the dashboard"
        description="The widget builder previews your changes in real time."
      >
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            Open{' '}
            <a
              href={`${DASHBOARD_URL}/widget`}
              className="text-primary underline"
              rel="noreferrer noopener"
            >
              Widget
            </a>{' '}
            to edit theme presets, custom colors, logo, avatar, welcome message, suggested questions
            and launcher position.
          </li>
          <li>
            Allowed domains are managed under{' '}
            <a
              href={`${DASHBOARD_URL}/widget`}
              className="text-primary underline"
              rel="noreferrer noopener"
            >
              Widget → Allowed domains
            </a>{' '}
            — see{' '}
            <Link href="/docs/embed#allowlist" className="text-primary underline">
              Embed → Domain allowlist setup
            </Link>{' '}
            for matching rules.
          </li>
        </ul>
      </DocSection>

      <DocSection title="How updates propagate" description="What happens after you save.">
        <p className="text-sm text-muted-foreground">
          The public config endpoint caches responses for up to 5 minutes, so most changes reach
          your visitors within moments — no redeploy or re-embed needed. Setting{' '}
          <code className="font-mono text-xs">enabled</code> to{' '}
          <code className="font-mono text-xs">false</code> hides the widget immediately on cache
          expiry.
        </p>
      </DocSection>
    </DocsShell>
  );
}

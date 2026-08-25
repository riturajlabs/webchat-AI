import type { Metadata } from 'next';
import Link from 'next/link';

import { DocHeader, DocSection } from '@/components/marketing/docs-ui';

export const metadata: Metadata = {
  title: 'Configuration',
  description:
    'Every WebChat AI widget configuration option — theming, behavior, suggested questions and domain allowlist.',
};

const CONFIG_OPTIONS: { key: string; values: string; description: string }[] = [
  { key: 'theme', values: 'light | dark | auto', description: 'Color scheme of the widget.' },
  {
    key: 'position',
    values: 'bottom-right | bottom-left',
    description: 'Corner of the viewport where the launcher sits.',
  },
  {
    key: 'primary_color',
    values: '#rrggbb',
    description: 'Primary action color (launcher, send button, header).',
  },
  { key: 'accent_color', values: '#rrggbb', description: 'Secondary accent color.' },
  { key: 'font_size', values: 'sm | md | lg', description: 'Base font size inside the chat.' },
  { key: 'logo_url', values: 'https://…', description: 'Custom logo shown in the header.' },
  { key: 'avatar_url', values: 'https://…', description: 'Assistant avatar image.' },
  {
    key: 'welcome_message',
    values: 'text',
    description: 'Greeting shown above the first message.',
  },
  { key: 'placeholder', values: 'text', description: 'Composer placeholder text.' },
  {
    key: 'suggested_questions',
    values: 'string[] (max 5)',
    description: 'Quick-prompt chips offered to new visitors.',
  },
  {
    key: 'branding',
    values: 'true | false',
    description: 'Show the "Powered by WebChat AI" badge.',
  },
  {
    key: 'dark_mode',
    values: 'true | false',
    description: 'Force the dark theme regardless of the visitor system theme.',
  },
  {
    key: 'auto_open',
    values: 'true | false',
    description: 'Open the chat automatically for new visitors.',
  },
  {
    key: 'enabled',
    values: 'true | false',
    description: 'Hide the widget from the page entirely.',
  },
  {
    key: 'allowed_domains',
    values: 'string[] (max 50)',
    description:
      'Origins permitted to embed the widget. Empty = blocked until configured; use "*" for open embedding.',
  },
];

export default function ConfigurationPage() {
  return (
    <div className="flex flex-col gap-6">
      <DocHeader
        title="Configuration"
        lede="Every field is editable from the dashboard widget builder (PATCH /api/websites/{id}/widget), with changes reflected instantly in the live preview."
      />

      <DocSection
        title="Options"
        description="Values are validated by the API; invalid payloads return an error."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">WebChat AI widget configuration options</caption>
            <thead>
              <tr className="border-b text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Option
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Values
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  Description
                </th>
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
        <p className="text-sm text-muted-foreground">
          Theme presets bundle several of these fields into curated palettes — see the dashboard
          widget builder. Embedding rules for{' '}
          <code className="font-mono text-xs">allowed_domains</code> are described in{' '}
          <Link
            href="/docs/embed#domains"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed → Domain allowlist
          </Link>
          .
        </p>
      </DocSection>
    </div>
  );
}

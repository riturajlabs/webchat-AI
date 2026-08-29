import Link from 'next/link';

import {
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  InlineCode,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/configuration',
  title: 'Configuration',
  description:
    'Every WebChat AI widget configuration option — theming, behavior, appearance, suggested questions and domain allowlist.',
});

interface ConfigOption {
  key: string;
  type: string;
  description: string;
  default?: string;
}

const GROUPS: { title: string; id: string; options: ConfigOption[] }[] = [
  {
    title: 'Theme',
    id: 'theme',
    options: [
      { key: 'theme', type: 'light | dark | auto', description: 'Color scheme of the widget.' },
      {
        key: 'theme_preset',
        type: 'preset id',
        description:
          'Curated palette id. Empty string (classic) uses the fully custom colors below.',
      },
      {
        key: 'primary_color',
        type: '#rrggbb',
        description: 'Primary action color (launcher, send button, header).',
      },
      {
        key: 'accent_color',
        type: '#rrggbb',
        description: 'Secondary accent color.',
      },
      { key: 'font_size', type: 'sm | md | lg', description: 'Base font size inside the chat.' },
      {
        key: 'dark_mode',
        type: 'true | false',
        description: 'Force the dark theme regardless of the visitor system theme.',
      },
      {
        key: 'font_family',
        type: 'string | null',
        description: 'UI font family; null uses the system stack.',
      },
    ],
  },
  {
    title: 'Appearance',
    id: 'appearance',
    options: [
      {
        key: 'logo_url',
        type: 'https://… | null',
        description: 'Custom logo shown in the header.',
      },
      { key: 'avatar_url', type: 'https://… | null', description: 'Assistant avatar image.' },
      {
        key: 'bot_name',
        type: 'string',
        description: 'Bot name shown in the widget header.',
      },
      {
        key: 'bot_status_text',
        type: 'string',
        description: 'Presence line under the bot name (e.g. "Online", "Away").',
      },
      {
        key: 'header_color',
        type: '#rrggbb | null',
        description: 'Header background; null uses the primary/secondary gradient.',
      },
      {
        key: 'secondary_color',
        type: '#rrggbb | null',
        description: 'Gradient partner for the primary color; null uses accent.',
      },
      {
        key: 'background_color',
        type: '#rrggbb | null',
        description: 'Window surface color; null uses the theme default.',
      },
      {
        key: 'text_color',
        type: '#rrggbb | null',
        description: 'Primary text color; null uses the theme default.',
      },
    ],
  },
  {
    title: 'Behavior',
    id: 'behavior',
    options: [
      {
        key: 'position',
        type: 'bottom-right | bottom-left',
        description: 'Corner of the viewport where the launcher sits.',
      },
      {
        key: 'welcome_message',
        type: 'text',
        description: 'Greeting shown above the first message.',
      },
      { key: 'placeholder', type: 'text', description: 'Composer placeholder text.' },
      {
        key: 'suggested_questions',
        type: 'string[] (max 5)',
        description: 'Quick-prompt chips offered to new visitors.',
      },
      {
        key: 'branding',
        type: 'true | false',
        description: 'Show the "Powered by WebChat AI" badge.',
      },
      {
        key: 'auto_open',
        type: 'true | false',
        description: 'Open the chat automatically for new visitors.',
      },
      {
        key: 'enabled',
        type: 'true | false',
        description: 'Hide the widget from the page entirely.',
      },
    ],
  },
  {
    title: 'Layout',
    id: 'layout',
    options: [
      {
        key: 'width',
        type: 'CSS length',
        description: 'Window width as a CSS length (px/em/rem/vh/vw/%).',
      },
      {
        key: 'height',
        type: 'CSS length',
        description: 'Window height as a CSS length (px/em/rem/vh/vw/%).',
      },
      {
        key: 'border_radius',
        type: 'CSS length',
        description: 'Window/launcher corner radius (px/em/rem/%).',
      },
      {
        key: 'launcher_size',
        type: 'CSS length',
        description: 'Launcher button size (px/em/rem/%).',
      },
    ],
  },
  {
    title: 'Access',
    id: 'access',
    options: [
      {
        key: 'allowed_domains',
        type: 'string[] (max 50)',
        description:
          'Origins permitted to embed the widget. Empty = blocked until configured; use "*" for open embedding.',
      },
    ],
  },
];

const THEME_PRESETS = [
  'ocean-blue',
  'midnight-dark',
  'emerald-support',
  'purple-ai',
  'minimal-white',
  'sunset',
  'modern-gradient',
];

export default function ConfigurationPage() {
  return (
    <div className="flex flex-col gap-8">
      <DocHeader
        breadcrumb="Customization / Configuration"
        title="Configuration"
        lede="Every field is editable from the dashboard widget builder (PATCH /api/websites/{id}/widget), with changes reflected instantly in the live preview."
      />

      <Callout variant="info" title="Where to edit">
        All options are managed from the dashboard&apos;s widget builder. Values are validated by
        the API; invalid payloads return a structured error.
      </Callout>

      {GROUPS.map((group) => (
        <DocSection key={group.id} id={group.id} title={group.title}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{group.title} configuration options</caption>
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
                {group.options.map(({ key, type, description }) => (
                  <tr key={key} className="border-b last:border-0 align-top">
                    <td className="py-1.5 pr-3 font-mono text-xs">{key}</td>
                    <td className="py-1.5 pr-3 font-mono text-xs text-muted-foreground">{type}</td>
                    <td className="py-1.5 text-muted-foreground">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DocSection>
      ))}

      <DocSection
        id="theme-presets"
        title="Theme presets"
        description="Curated palettes that bundle several appearance fields into one id."
      >
        <Bullets
          items={THEME_PRESETS.map((preset) => (
            <InlineCode key={preset}>{preset}</InlineCode>
          ))}
        />
        <p className="text-sm text-muted-foreground">
          An empty <InlineCode>theme_preset</InlineCode> clears the preset and returns to the fully
          custom classic colors.
        </p>
      </DocSection>

      <DocSection
        id="validation"
        title="Validation limits"
        description="The API enforces these bounds on the fields above."
      >
        <Bullets
          items={[
            <>
              <InlineCode>suggested_questions</InlineCode> — at most 5, each up to 200 characters.
            </>,
            <>
              <InlineCode>allowed_domains</InlineCode> — at most 50 entries.
            </>,
            <>
              <InlineCode>welcome_message</InlineCode> — up to 500 characters.
            </>,
            <>
              <InlineCode>placeholder</InlineCode> — up to 120 characters.
            </>,
            <>
              <InlineCode>bot_name</InlineCode> (60) and <InlineCode>bot_status_text</InlineCode>{' '}
              (40) — short presence strings.
            </>,
            <>
              <InlineCode>logo_url</InlineCode> and <InlineCode>avatar_url</InlineCode> — up to 2048
              characters.
            </>,
            <>
              <InlineCode>width</InlineCode>, <InlineCode>height</InlineCode>,{' '}
              <InlineCode>border_radius</InlineCode> and <InlineCode>launcher_size</InlineCode> —
              CSS lengths up to 20 characters.
            </>,
          ]}
        />
      </DocSection>

      <DocSection
        id="domain-rules"
        title="Domain rules"
        description="How allowed_domains controls embedding."
      >
        <p className="text-sm text-muted-foreground">
          Embedding rules for <InlineCode>allowed_domains</InlineCode> are described in{' '}
          <Link
            href="/docs/embed#domains"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed &rarr; Domain allowlist
          </Link>
          .
        </p>
      </DocSection>
    </div>
  );
}

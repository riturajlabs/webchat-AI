import {
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/configuration',
  title: 'Configuration Reference',
  description:
    'Full reference of all WebChat AI widget configuration parameters, accepted values, 11 theme presets, 10 fonts, and API validation limits.',
});

interface ConfigOption {
  key: string;
  type: string;
  defaultVal: string;
  description: string;
}

const GROUPS: { title: string; id: string; options: ConfigOption[] }[] = [
  {
    title: 'Theme & Typography',
    id: 'theme',
    options: [
      {
        key: 'theme',
        type: "'light' | 'dark' | 'auto'",
        defaultVal: "'light'",
        description:
          'Base color mode. "auto" follows the visitor\'s operating system prefers-color-scheme.',
      },
      {
        key: 'theme_preset',
        type: 'preset id',
        defaultVal: "'' (classic)",
        description:
          'Curated palette preset id (11 options available). Empty string uses the custom classic palette.',
      },
      {
        key: 'primary_color',
        type: '#rrggbb (hex)',
        defaultVal: '#10A37F',
        description: 'Primary action color for the launcher icon, header, and send button.',
      },
      {
        key: 'accent_color',
        type: '#rrggbb (hex)',
        defaultVal: '#25D366',
        description: 'Secondary accent color for badges and highlights.',
      },
      {
        key: 'font_size',
        type: "'sm' | 'md' | 'lg'",
        defaultVal: "'md'",
        description: 'Base font size inside the chat window (14px, 16px, or 18px).',
      },
      {
        key: 'dark_mode',
        type: 'boolean',
        defaultVal: 'false',
        description: 'Force dark theme mode regardless of the visitor system setting.',
      },
      {
        key: 'font_family',
        type: 'string | null',
        defaultVal: 'null',
        description:
          'Font family stack. Null uses system default. Accepts any of the 10 curated typography options.',
      },
    ],
  },
  {
    title: 'Appearance & Identity',
    id: 'appearance',
    options: [
      {
        key: 'bot_name',
        type: 'string (max 60)',
        defaultVal: "'AI Assistant'",
        description: 'Assistant name displayed in the top header and message bubbles.',
      },
      {
        key: 'bot_status_text',
        type: 'string (max 40)',
        defaultVal: "'Online'",
        description: 'Presence indicator line under the bot name.',
      },
      {
        key: 'logo_url',
        type: 'https://... | null',
        defaultVal: 'null',
        description: 'Brand logo displayed in the widget header.',
      },
      {
        key: 'avatar_url',
        type: 'https://... | null',
        defaultVal: 'null',
        description: 'Image avatar URL displayed next to bot messages.',
      },
      {
        key: 'header_color',
        type: '#rrggbb | null',
        defaultVal: 'null',
        description: 'Custom header background color; null uses the theme preset default.',
      },
      {
        key: 'secondary_color',
        type: '#rrggbb | null',
        defaultVal: 'null',
        description: 'Secondary gradient color; null uses accent color.',
      },
      {
        key: 'background_color',
        type: '#rrggbb | null',
        defaultVal: 'null',
        description: 'Chat window surface color; null uses theme default.',
      },
      {
        key: 'text_color',
        type: '#rrggbb | null',
        defaultVal: 'null',
        description: 'Primary text color; null uses theme default.',
      },
    ],
  },
  {
    title: 'Behavior & Engagement',
    id: 'behavior',
    options: [
      {
        key: 'position',
        type: "'bottom-right' | 'bottom-left'",
        defaultVal: "'bottom-right'",
        description: 'Corner of the browser viewport where the launcher sits.',
      },
      {
        key: 'welcome_message',
        type: 'string (max 500)',
        defaultVal: "'Hi! How can I help you today?'",
        description: 'Greeting message displayed above the first visitor turn.',
      },
      {
        key: 'placeholder',
        type: 'string (max 120)',
        defaultVal: "'Type your message...'",
        description: 'Input composer placeholder text.',
      },
      {
        key: 'suggested_questions',
        type: 'string[] (max 5)',
        defaultVal: '[]',
        description: 'Quick-prompt suggestion chips offered to new visitors (max 200 chars each).',
      },
      {
        key: 'branding',
        type: 'boolean',
        defaultVal: 'true',
        description: 'Display the "Powered by WebChat AI" attribution link in the footer.',
      },
      {
        key: 'auto_open',
        type: 'boolean',
        defaultVal: 'false',
        description: 'Automatically open the chat window when a new visitor lands on the page.',
      },
      {
        key: 'enabled',
        type: 'boolean',
        defaultVal: 'true',
        description: 'Master toggle. When false, the widget does not render on host pages.',
      },
    ],
  },
  {
    title: 'Dimensions & Layout',
    id: 'layout',
    options: [
      {
        key: 'width',
        type: 'CSS length (max 20)',
        defaultVal: "'400px'",
        description:
          'Chat window width (supports px, rem, vw). Enforces responsive mobile constraints.',
      },
      {
        key: 'height',
        type: 'CSS length (max 20)',
        defaultVal: "'640px'",
        description: 'Chat window height (supports px, rem, vh).',
      },
      {
        key: 'border_radius',
        type: 'CSS length (max 20)',
        defaultVal: "'16px'",
        description: 'Corner radius for the chat window container.',
      },
      {
        key: 'launcher_size',
        type: 'CSS length (max 20)',
        defaultVal: "'56px'",
        description: 'Diameter of the floating launcher action button.',
      },
    ],
  },
  {
    title: 'Origin Security',
    id: 'access',
    options: [
      {
        key: 'allowed_domains',
        type: 'string[] (max 50)',
        defaultVal: 'auto-seeded',
        description:
          'Hostnames permitted to embed this widget (e.g. "example.com", "*.example.com"). Unlisted origins receive 403.',
      },
    ],
  },
];

const THEME_PRESETS = [
  'classic',
  'whatsapp-classic',
  'ios-native',
  'enterprise-slate',
  'ocean-blue',
  'midnight-dark',
  'emerald-support',
  'purple-ai',
  'minimal-white',
  'sunset',
  'modern-gradient',
];

const FONTS = [
  'system',
  'inter',
  'poppins',
  'nunito',
  'roboto',
  'open-sans',
  'montserrat',
  'lato',
  'playfair-display',
  'space-grotesk',
];

export default function ConfigurationPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[{ label: 'Widget', href: '/docs/embed' }, { label: 'Configuration' }]}
        title="Widget Configuration Reference"
        lede="Complete reference of all widget configuration properties, types, defaults, and API validation bounds."
      />

      <Callout variant="info" title="Where settings are edited">
        All properties can be configured interactively from the dashboard Widget Builder, or
        programmatically via <InlineCode>PATCH /api/websites/{'{id}'}/widget</InlineCode>.
      </Callout>

      {GROUPS.map((group) => (
        <DocSection key={group.id} id={group.id} title={group.title}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{group.title} options</caption>
              <thead>
                <tr className="border-b border-border/80 text-muted-foreground">
                  <th scope="col" className="py-2 pr-3 font-semibold">
                    Option
                  </th>
                  <th scope="col" className="py-2 pr-3 font-semibold">
                    Type
                  </th>
                  <th scope="col" className="py-2 pr-3 font-semibold">
                    Default
                  </th>
                  <th scope="col" className="py-2 font-semibold">
                    Description
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.options.map(({ key, type, defaultVal, description }) => (
                  <tr key={key} className="border-b border-border/50 last:border-0 align-top">
                    <td className="py-2 pr-3 font-mono text-xs font-semibold text-foreground">
                      {key}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-blue-600 dark:text-blue-400">
                      {type}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                      {defaultVal}
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DocSection>
      ))}

      {/* 11 Theme Presets */}
      <DocSection
        id="theme-presets"
        title="Available theme preset IDs (11 total)"
        description="Curated color palettes bundling header, surface, bubble, and text tokens."
      >
        <div className="flex flex-wrap gap-2">
          {THEME_PRESETS.map((preset) => (
            <span
              key={preset}
              className="rounded bg-muted px-2.5 py-1 font-mono text-xs text-foreground border border-border/60"
            >
              {preset}
            </span>
          ))}
        </div>
      </DocSection>

      {/* 10 Font Keys */}
      <DocSection
        id="typography-keys"
        title="Available typography options (10 total)"
        description="On-demand curated font families loaded securely via Google Fonts."
      >
        <div className="flex flex-wrap gap-2">
          {FONTS.map((font) => (
            <span
              key={font}
              className="rounded bg-muted px-2.5 py-1 font-mono text-xs text-blue-600 dark:text-blue-400 border border-border/60"
            >
              {font}
            </span>
          ))}
        </div>
      </DocSection>

      {/* Validation Rules */}
      <DocSection
        id="validation-rules"
        title="Validation bounds &amp; limits"
        description="Constraints enforced by the REST API."
      >
        <Bullets
          items={[
            <>
              <InlineCode>bot_name</InlineCode>: String between 1 and 60 characters.
            </>,
            <>
              <InlineCode>bot_status_text</InlineCode>: String up to 40 characters.
            </>,
            <>
              <InlineCode>welcome_message</InlineCode>: String up to 500 characters.
            </>,
            <>
              <InlineCode>placeholder</InlineCode>: String up to 120 characters.
            </>,
            <>
              <InlineCode>suggested_questions</InlineCode>: Array of up to 5 items; each question
              max 200 characters.
            </>,
            <>
              <InlineCode>allowed_domains</InlineCode>: Array of up to 50 hostname patterns.
            </>,
            <>
              <InlineCode>logo_url</InlineCode> and <InlineCode>avatar_url</InlineCode>: HTTPS URLs
              up to 2048 characters.
            </>,
            <>
              <InlineCode>width</InlineCode>, <InlineCode>height</InlineCode>,{' '}
              <InlineCode>border_radius</InlineCode>, <InlineCode>launcher_size</InlineCode>: Valid
              CSS lengths up to 20 characters.
            </>,
          ]}
        />
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Customization Guide',
            description: 'Visual overview of presets, typography, and palette overrides.',
            href: '/docs/customization',
          },
          {
            title: 'Embed & Security Guide',
            description: 'How allowed_domains and CSP protect your widget.',
            href: '/docs/embed',
          },
          {
            title: 'API Reference',
            description: 'Learn how to update widget configuration programmatically.',
            href: '/docs/api',
          },
        ]}
      />
    </div>
  );
}

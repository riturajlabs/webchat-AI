import {
  Callout,
  DocHeader,
  DocSection,
  RelatedDocs,
  ScreenshotFrame,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/customization',
  title: 'Widget Customization & Themes',
  description:
    'Customize your WebChat AI widget appearance: 11 curated theme presets, 10 Google Fonts typography choices, custom color overrides, bot branding, and dimensions.',
});

const THEMES = [
  {
    id: 'classic',
    name: 'Classic',
    desc: 'Default emerald and teal palette with clean white surfaces.',
  },
  {
    id: 'whatsapp-classic',
    name: 'WhatsApp Classic',
    desc: 'Familiar messaging aesthetic with teal headers and green bubbles.',
  },
  {
    id: 'ios-native',
    name: 'iOS Native',
    desc: 'Clean, native iOS messaging feel with crisp blue bubbles.',
  },
  {
    id: 'enterprise-slate',
    name: 'Enterprise Slate',
    desc: 'Professional, high-contrast theme optimized for long reading sessions.',
  },
  { id: 'ocean-blue', name: 'Ocean Blue', desc: 'Trusted SaaS blue with crisp white surfaces.' },
  {
    id: 'midnight-dark',
    name: 'Midnight Dark',
    desc: 'Bold dark-first theme for a modern product vibe.',
  },
  {
    id: 'emerald-support',
    name: 'Emerald Support',
    desc: 'Friendly green for support and success teams.',
  },
  { id: 'purple-ai', name: 'Purple AI', desc: 'Violet accents for AI assistants and innovation.' },
  { id: 'minimal-white', name: 'Minimal White', desc: 'Clean monochrome that fits any brand.' },
  { id: 'sunset', name: 'Sunset', desc: 'Warm orange and red for friendly, approachable brands.' },
  {
    id: 'modern-gradient',
    name: 'Modern Gradient',
    desc: 'Vivid primary-to-accent gradient header.',
  },
];

const FONTS = [
  { key: 'system', name: 'System Default', type: 'San Francisco, Segoe UI, Roboto, sans-serif' },
  { key: 'inter', name: 'Inter', type: 'Clean, neutral geometric sans-serif' },
  { key: 'poppins', name: 'Poppins', type: 'Friendly, modern rounded geometric sans-serif' },
  { key: 'nunito', name: 'Nunito', type: 'Soft, rounded sans-serif with excellent legibility' },
  { key: 'roboto', name: 'Roboto', type: 'Neo-grotesque sans-serif with natural reading rhythm' },
  { key: 'open-sans', name: 'Open Sans', type: 'Humanist sans-serif with open letterforms' },
  { key: 'montserrat', name: 'Montserrat', type: 'Distinct urban architectural sans-serif' },
  { key: 'lato', name: 'Lato', type: 'Warm, corporate sans-serif with sleek curves' },
  {
    key: 'playfair-display',
    name: 'Playfair Display',
    type: 'Sophisticated modern serif for premium editorial feel',
  },
  {
    key: 'space-grotesk',
    name: 'Space Grotesk',
    type: 'Tech-focused monospace-inspired proportional sans-serif',
  },
];

export default function CustomizationPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[{ label: 'Widget', href: '/docs/embed' }, { label: 'Customization' }]}
        title="Widget Customization &amp; Theming"
        lede="Style every aspect of your assistant to match your brand identity with curated themes, web fonts, and custom color overrides."
      />

      <ScreenshotFrame
        src="/docs-assets/screenshots/widget-customization.png"
        alt="WebChat AI Widget Customization Builder"
        caption="The dashboard Widget Builder includes real-time live preview for both desktop and mobile viewports."
        priority
      />

      {/* Theme Presets */}
      <DocSection
        id="theme-presets"
        title="11 Curated theme presets"
        description="One-click themes that instantly balance header gradients, bubble colors, surface tints, and text contrast."
      >
        <p className="text-sm text-muted-foreground">
          In the dashboard theme selector, the initial view displays 6 curated cards. Clicking{' '}
          <strong className="text-foreground">&quot;Show more (5 more)&quot;</strong> expands all 11
          themes, and <strong className="text-foreground">&quot;Show less&quot;</strong> collapses
          back to 6.
        </p>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {THEMES.map((t) => (
            <div key={t.id} className="rounded-lg border border-border/70 bg-card p-3.5 shadow-2xs">
              <p className="font-semibold text-sm text-foreground">{t.name}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t.desc}</p>
              <span className="mt-2 inline-block font-mono text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                preset: &quot;{t.id}&quot;
              </span>
            </div>
          ))}
        </div>
      </DocSection>

      {/* Typography System */}
      <DocSection
        id="typography"
        title="10 Curated font options"
        description="Visually distinctive typography loaded on-demand via Google Fonts."
      >
        <div className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>
            To prevent heavy font binary files from bloating the widget bundle (keeping it strictly
            under 50 kB gzip), WebChat AI loads web font stylesheets dynamically when configured:
          </p>

          <div className="grid gap-2 sm:grid-cols-2">
            {FONTS.map((f) => (
              <div
                key={f.key}
                className="flex items-center justify-between rounded-lg border border-border/60 p-3 bg-card"
              >
                <div>
                  <p className="font-semibold text-sm text-foreground">{f.name}</p>
                  <p className="text-xs text-muted-foreground">{f.type}</p>
                </div>
                <span className="font-mono text-xs text-blue-600 dark:text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">
                  {f.key}
                </span>
              </div>
            ))}
          </div>

          <Callout variant="info" title="Zero Bundled Binaries">
            No font binaries (.woff2) are embedded in the SDK package. If the visitor is offline or
            their network blocks Google Fonts, the widget seamlessly degrades to the native system
            font stack without visual breakage.
          </Callout>
        </div>
      </DocSection>

      {/* Brand Identity & Colors */}
      <DocSection
        id="branding-and-colors"
        title="Branding hierarchy &amp; colors"
        description="Override preset defaults with exact brand assets."
      >
        <div className="flex flex-col gap-4 text-sm text-muted-foreground">
          <p>
            You can override individual styling elements without altering the rest of your chosen
            preset:
          </p>
          <ul className="list-disc pl-5">
            <li>
              <strong className="text-foreground">Bot Name:</strong> Max 60 characters (e.g.
              &quot;Acme Support AI&quot;).
            </li>
            <li>
              <strong className="text-foreground">Status Presence Text:</strong> Max 40 characters
              (e.g. &quot;Online &bull; Answers in seconds&quot;).
            </li>
            <li>
              <strong className="text-foreground">Avatar URL:</strong> Image URL for the bot avatar
              inside chat messages and header.
            </li>
            <li>
              <strong className="text-foreground">Header Logo URL:</strong> Optional logo shown in
              the top navigation bar.
            </li>
            <li>
              <strong className="text-foreground">Color Overrides:</strong> Set custom HEX colors
              for Primary, Header Background, Window Surface, and Body Text.
            </li>
          </ul>
        </div>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Configuration Reference',
            description: 'Full list of widget parameters, types, and API validation limits.',
            href: '/docs/configuration',
          },
          {
            title: 'Staging & Testing Guide',
            description: 'Test your custom theme in the dashboard Widget Test page.',
            href: '/docs/testing',
          },
          {
            title: 'Embed Guide',
            description: 'Deploy the styled assistant to your website.',
            href: '/docs/embed',
          },
        ]}
      />
    </div>
  );
}

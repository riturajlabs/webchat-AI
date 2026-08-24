import type { Metadata } from 'next';
import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import { ALLOWLIST_EXAMPLE, DASHBOARD_URL, SCRIPT_TAG } from '@/features/docs/content';

import { DocsShell, DocSection } from '../_components/docs-shell';

export const metadata: Metadata = {
  title: 'Quickstart',
  description:
    'Create an account, register your website and embed the WebChat AI widget in five steps.',
};

export default function QuickstartPage() {
  return (
    <DocsShell active="/docs/quickstart">
      <header className="flex flex-col gap-3">
        <h1 className="font-sans text-3xl font-bold tracking-tight">Quickstart</h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          From signup to a live assistant on your site — five steps, no code beyond one script tag.
        </p>
      </header>

      <DocSection
        title="1. Create your account"
        description="Sign up with your email and verify your address to unlock the dashboard."
      >
        <p className="text-sm text-muted-foreground">
          Start free at{' '}
          <Link href="/signup" className="text-primary underline">
            the signup page
          </Link>
          . Every account gets its own isolated tenant for websites, knowledge bases and
          conversations.
        </p>
      </DocSection>

      <DocSection
        title="2. Register your website"
        description="Point WebChat AI at your public site URL."
      >
        <p className="text-sm text-muted-foreground">
          In the dashboard open{' '}
          <a
            href={`${DASHBOARD_URL}/websites`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Websites → Add website
          </a>{' '}
          and enter your URL. The crawler fetches your public pages, splits them into chunks, and
          builds a dedicated knowledge base for that site.
        </p>
      </DocSection>

      <DocSection
        title="3. Wait for indexing"
        description="Crawling, chunking and embedding run as background jobs."
      >
        <p className="text-sm text-muted-foreground">
          Watch progress under{' '}
          <a
            href={`${DASHBOARD_URL}/knowledge`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Knowledge Base
          </a>
          . Once pages are indexed, answers are generated from your content with source citations —
          and if nothing relevant is found, the assistant says so instead of guessing.
        </p>
      </DocSection>

      <DocSection
        title="4. Copy the embed script"
        description="One script tag is all your page needs."
      >
        <p className="text-sm text-muted-foreground">
          Open{' '}
          <a
            href={`${DASHBOARD_URL}/widget`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Widget → Widget embed code
          </a>{' '}
          and copy the snippet with your real widget id:
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy script tag" />
        <p className="text-sm text-muted-foreground">
          Paste it before the closing <code className="font-mono text-xs">&lt;/body&gt;</code> tag
          of your site. The <code className="font-mono text-xs">defer</code> attribute keeps it from
          blocking render, and the launcher appears once the bundle has run — no{' '}
          <code className="font-mono text-xs">init()</code> call required.
        </p>
      </DocSection>

      <DocSection
        title="5. Allowlist your domain"
        description="The widget only runs on origins you explicitly allow."
      >
        <p className="text-sm text-muted-foreground">
          New widgets are seeded with your registered hostname, so they work there out of the box.
          To allow more origins (or a subdomain wildcard), add bare hostnames under{' '}
          <a
            href={`${DASHBOARD_URL}/widget`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Widget → Allowed domains
          </a>
          :
        </p>
        <CodeBlock code={ALLOWLIST_EXAMPLE} language="text" copyLabel="Copy matching examples" />
        <p className="text-sm text-muted-foreground">
          Full details live in{' '}
          <Link href="/docs/embed#allowlist" className="text-primary underline">
            Embed → Domain allowlist setup
          </Link>
          , and every appearance option is listed in{' '}
          <Link href="/docs/configuration" className="text-primary underline">
            Configuration
          </Link>
          .
        </p>
      </DocSection>

      <DocSection title="Next steps" description="Where to go from here.">
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            Customize theme, logo and suggested questions in{' '}
            <Link href="/docs/configuration" className="text-primary underline">
              Configuration
            </Link>
            .
          </li>
          <li>
            Framework app? Use the SDK via <code className="font-mono text-xs">init()</code> or{' '}
            <code className="font-mono text-xs">mount()</code> — see{' '}
            <Link href="/docs/embed" className="text-primary underline">
              Embed
            </Link>
            .
          </li>
          <li>
            Automate website and conversation management with the{' '}
            <Link href="/docs/api" className="text-primary underline">
              REST API
            </Link>
            .
          </li>
        </ul>
      </DocSection>
    </DocsShell>
  );
}

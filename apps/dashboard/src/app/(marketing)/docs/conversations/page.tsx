import {
  BreadcrumbNav,
  Bullets,
  Callout,
  Checklist,
  DiagramBox,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/conversations',
  title: 'Conversations & visitor sessions',
  description:
    'Review visitor chat transcripts, source citations, per-message token metrics, latency breakdowns, and conversation lifecycle management in WebChat AI.',
});

export default function ConversationsDocPage() {
  return (
    <div className="flex flex-col gap-8">
      <BreadcrumbNav
        items={[
          { label: 'Documentation', href: '/docs' },
          { label: 'Manage' },
          { label: 'Conversations' },
        ]}
      />

      <DocHeader
        breadcrumb="Manage / Conversations"
        title="Conversations & visitor logs"
        lede="Inspect real visitor interactions with your AI assistants. Every visitor session captures full message transcripts, source citations, token consumption, and per-turn response latency."
      />

      <DocSection
        id="overview"
        title="Session architecture"
        description="How visitor sessions are generated, persisted, and tracked across widget interactions."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          When an end user opens the widget on your site, the widget client establishes a unique
          session identifier with the WebChat AI backend. This session groups consecutive
          question-answer turns into a cohesive conversation thread, allowing the assistant to
          maintain conversational context while isolating data per visitor.
        </p>

        <DiagramBox
          title="Conversation Turn Lifecycle"
          description="The 4 stages from visitor input to persisted telemetry."
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                STAGE 1
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Visitor Message</p>
              <p className="mt-1 text-xs text-muted-foreground">
                User types question in widget; client sends payload with active session token.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                STAGE 2
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">RAG Retrieval</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Context retrieved from vector + lexical indexes; source citations assigned.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                STAGE 3
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Generation & Telemetry</p>
              <p className="mt-1 text-xs text-muted-foreground">
                LLM generates reply; backend records input tokens, output tokens, and latency.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                STAGE 4
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Dashboard Sync</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Session transcripts and metrics immediately surface in the dashboard inbox.
              </p>
            </div>
          </div>
        </DiagramBox>
      </DocSection>

      <DocSection
        id="dashboard-inbox"
        title="Navigating the inbox"
        description="Searching, filtering, and reviewing visitor conversation history."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          The Conversations dashboard (<InlineCode>/conversations</InlineCode>) provides an inbox
          view of all visitor interactions across your registered assistants:
        </p>

        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Assistant Filter:</strong> Switch
              between all assistants or isolate conversations for a specific website or
              document-based assistant.
            </>,
            <>
              <strong className="font-medium text-foreground">Real-Time Search:</strong> Debounced
              (300ms) full-text search across message content, visitor labels, and session IDs.
            </>,
            <>
              <strong className="font-medium text-foreground">Status Badges:</strong> Identifies
              active sessions, completed threads, and partial responses where generation encountered
              upstream timeouts.
            </>,
            <>
              <strong className="font-medium text-foreground">Pagination:</strong> Paginated at 20
              conversations per page with immediate total counts and server-side navigation.
            </>,
          ]}
        />
      </DocSection>

      <DocSection
        id="inspecting-turns"
        title="Message details & telemetry"
        description="Auditing source grounding, citations, and model performance on every turn."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          Clicking any conversation opens the detailed transcript viewer. Each assistant message
          exposes the underlying facts and operational telemetry:
        </p>

        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Message turn telemetry fields</caption>
            <thead className="bg-muted/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Telemetry Metric
                </th>
                <th scope="col" className="px-4 py-3">
                  Example
                </th>
                <th scope="col" className="px-4 py-3">
                  Description
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60 font-mono text-xs">
              <tr>
                <td className="px-4 py-3 font-medium text-foreground font-sans">
                  Source Citations
                </td>
                <td className="px-4 py-3 text-blue-600 dark:text-blue-400">[1] /docs/pricing</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Direct hyperlinks to crawled pages or uploaded documents grounding the answer.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-foreground font-sans">Input Tokens</td>
                <td className="px-4 py-3 text-foreground">412 tokens</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Prompt tokens including system prompt, grounded chunks, and conversation history.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-foreground font-sans">Output Tokens</td>
                <td className="px-4 py-3 text-foreground">86 tokens</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Completion tokens generated by the model for this specific reply.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-foreground font-sans">Response Time</td>
                <td className="px-4 py-3 text-foreground">340ms / 1.4s</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  End-to-end turn duration from question submission to stream completion.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 font-medium text-foreground font-sans">Message Status</td>
                <td className="px-4 py-3 text-emerald-600 dark:text-emerald-400">
                  completed / failed
                </td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Flags partial answers if generation was aborted or hit provider rate limits.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection
        id="privacy-and-retention"
        title="Privacy & conversation deletion"
        description="Tenant data ownership and compliance controls."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          Conversations belong entirely to your tenant account. You can permanently delete any
          conversation session directly from the detail view:
        </p>

        <Checklist
          items={[
            <>
              <strong className="font-medium text-foreground">Hard Deletion:</strong> Deleting a
              session immediately removes all associated user messages, assistant responses, source
              links, and token logs from the database.
            </>,
            <>
              <strong className="font-medium text-foreground">Multi-Tenant Isolation:</strong>{' '}
              Conversation queries are strictly scoped by tenant_id. Cross-tenant reads or mutations
              return 404 or 403.
            </>,
            <>
              <strong className="font-medium text-foreground">No End-User PII Required:</strong> By
              default, visitors are tracked with anonymous pseudorandom session tokens without
              requiring cookies or personal identification.
            </>,
          ]}
        />

        <Callout variant="tip" title="Auditing AI Quality">
          When visitors ask questions that trigger the ungrounded answer fallback (e.g. &ldquo;I do
          not have enough information&rdquo;), use those questions to identify missing content and
          upload supplemental PDFs or trigger website re-crawls.
        </Callout>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Analytics & usage',
            href: '/docs/analytics',
            description: 'Inspect aggregated chat volume, top questions, and token costs.',
          },
          {
            title: 'RAG & grounding pipeline',
            href: '/docs/rag-pipeline',
            description: 'Understand how chunks and citations are selected during retrieval.',
          },
          {
            title: 'REST API reference',
            href: '/docs/api',
            description:
              'Access conversation transcripts programmatically via GET /api/conversations.',
          },
        ]}
      />
    </div>
  );
}

import { Callout, DocHeader, DocSection, RelatedDocs } from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/rag-pipeline',
  title: 'RAG & Retrieval Grounding',
  description:
    'Deep dive into the WebChat AI retrieval-augmented generation engine: hybrid search, Reciprocal Rank Fusion, confidence scoring, and grounded responses.',
});

export default function RagPipelinePage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[
          { label: 'Knowledge', href: '/docs/knowledge-sources' },
          { label: 'RAG & Grounding' },
        ]}
        title="RAG &amp; Answer Grounding Engine"
        lede="How WebChat AI transforms visitor questions into grounded, source-backed answers without fabricating unverified information."
      />

      <Callout variant="info" title="What is Retrieval-Augmented Generation (RAG)?">
        RAG connects general-purpose Large Language Models (LLMs) to your specific documentation.
        Rather than relying on the LLM&apos;s pre-trained memory, WebChat AI searches your indexed
        knowledge base, retrieves the most relevant passages, and feeds them directly into the
        context window as authoritative evidence.
      </Callout>

      {/* Step-by-Step Question Flow */}
      <DocSection
        id="question-lifecycle"
        title="What happens when a visitor asks a question?"
        description="The 8-stage pipeline executed per user message."
      >
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 1 &bull; SANITIZATION &amp; INJECTION GUARD
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Input Validation &amp; Safety Screening
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Incoming questions are trimmed, sanitized, and evaluated against common prompt
              injection patterns. The system rejects abusive payloads before any embedding or
              generation compute is spent.
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 2 &bull; QUERY REWRITING &amp; MEMORY
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">Context-Aware Disambiguation</p>
            <p className="mt-1 text-xs text-muted-foreground">
              If the user asks a follow-up question (e.g. &quot;How much does it cost?&quot;), the
              query rewriter uses prior conversation memory to expand pronouns and implicit
              references into a self-contained search query.
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 3 &bull; HYBRID SEARCH RETRIEVAL
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Dual-Path Vector + Lexical Search
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              WebChat AI retrieves passages using two complementary strategies:
            </p>
            <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
              <li>
                <strong className="text-foreground">Dense Vector Search:</strong> Measures cosine
                similarity against chunk embeddings using the tenant&apos;s locked embedding
                provider.
              </li>
              <li>
                <strong className="text-foreground">Lexical Frequency Matching:</strong> Evaluates
                token frequency, inverse document frequency (IDF), and passage length normalization.
              </li>
            </ul>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 4 &bull; RECIPROCAL RANK FUSION (RRF) &amp; RERANKING
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Merging and Reordering Candidate Chunks
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Results from vector search and lexical search are merged using Reciprocal Rank Fusion
              (RRF) and scored with embedding-based reranking with lexical awareness. A maximum
              chunk limit per source prevents a single document from crowding out others.
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 5 &bull; CONFIDENCE &amp; ANSWERABILITY ASSESSMENT
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">The Hallucination Guard</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Before calling the language model, the system evaluates chunk relevance scores. If the
              knowledge base contains no sufficiently relevant material, the assistant returns a
              graceful fallback message immediately without invoking the LLM, ensuring ungrounded
              facts are not fabricated.
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 6 &bull; CONTEXT OPTIMIZATION
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Deduplication &amp; Character Budgets
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Retrieved chunks are stripped of near-duplicates and compressed to fit within a strict
              context character budget. This reduces latency and ensures only high-signal
              information reaches the model.
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 7 &bull; STREAMING GENERATION
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Server-Sent Events (SSE) Output
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              The model synthesizes the answer strictly based on the provided context passages.
              Tokens stream back to the widget UI in real time over Server-Sent Events (SSE).
            </p>
          </div>

          <div className="rounded-lg border border-border/70 p-4 bg-card">
            <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
              STAGE 8 &bull; CITATION GROUNDING
            </span>
            <p className="mt-1 text-sm text-foreground font-medium">
              Traceable Document Attribution
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Every factual response includes structured source cards linking visitors directly to
              the crawled web URL or uploaded document that supplied the evidence.
            </p>
          </div>
        </div>
      </DocSection>

      {/* Provider Consistency Lock */}
      <DocSection
        id="provider-lock"
        title="Ingestion provider locking"
        description="Preventing vector space corruption across re-crawls."
      >
        <p className="text-sm text-muted-foreground">
          When an assistant first indexes content, WebChat AI permanently records the embedding
          provider, model, and vector dimensions on the website record. All subsequent document
          uploads, retries, and visitor search queries are locked to that identical model. This
          ensures vector search spaces never suffer dimensionality or semantic drift.
        </p>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Knowledge Sources Guide',
            description: 'Learn how to configure website crawls and uploaded files.',
            href: '/docs/knowledge-sources',
          },
          {
            title: 'Conversations & Citations',
            description:
              'Inspect live visitor conversation transcripts and retrieved source chunks.',
            href: '/docs/conversations',
          },
          {
            title: 'Security & Tenant Isolation',
            description: 'How tenant data is completely isolated in vector databases.',
            href: '/docs/security',
          },
        ]}
      />
    </div>
  );
}

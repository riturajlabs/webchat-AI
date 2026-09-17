import { RefreshCw, Trash2 } from 'lucide-react';

import {
  DiagramBox,
  DocHeader,
  DocSection,
  RelatedDocs,
  ScreenshotFrame,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/document-upload',
  title: 'File Uploads & Processing',
  description:
    'Complete guide to uploading documents to WebChat AI: supported file formats, size bounds, processing lifecycles, and retry procedures.',
});

const LIMITS = [
  {
    item: 'Supported formats',
    limit: '.pdf, .docx, .md, .txt',
    note: 'Validated via magic bytes and MIME types',
  },
  {
    item: 'Max files per upload batch',
    limit: '5 files',
    note: 'Enforced on POST /api/knowledge/.../upload',
  },
  { item: 'Max file size', limit: '10 MB', note: 'Applies per file and per total upload batch' },
  {
    item: 'PDF page ceiling',
    limit: '100 pages',
    note: 'Larger PDFs must be split prior to upload',
  },
  {
    item: 'Encrypted / Password PDFs',
    limit: 'Rejected',
    note: 'DocumentPasswordProtectedError returned',
  },
  {
    item: 'Extracted characters range',
    limit: '50 to 500,000 chars',
    note: 'Scanned image-only PDFs require OCR first',
  },
  {
    item: 'Chunk token target',
    limit: '500–800 tokens',
    note: '100-token overlap between adjacent chunks',
  },
];

const STATUSES = [
  {
    status: 'pending',
    variant: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
    description: 'File has been uploaded and queued for background text extraction.',
  },
  {
    status: 'processing',
    variant: 'bg-blue-500/10 text-blue-700 dark:text-blue-400',
    description:
      'Text has been extracted and is actively undergoing chunking and vector embedding generation.',
  },
  {
    status: 'completed',
    variant: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
    description:
      'All chunks have been embedded and stored in the tenant vector index. Ready for retrieval.',
  },
  {
    status: 'failed',
    variant: 'bg-red-500/10 text-red-700 dark:text-red-400',
    description:
      'Processing failed (e.g. corruption, password protection, or rate limit). Manual retry is available.',
  },
  {
    status: 'rate_limited',
    variant: 'bg-purple-500/10 text-purple-700 dark:text-purple-400',
    description:
      'Embedding API quota was temporarily reached. Will retry automatically with exponential backoff.',
  },
];

export default function DocumentUploadPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[
          { label: 'Knowledge', href: '/docs/knowledge-sources' },
          { label: 'File Uploads' },
        ]}
        title="Document Uploads &amp; Processing"
        lede="Upload proprietary documents directly into your assistant's knowledge base with automated text extraction, chunking, and embedding."
      />

      <ScreenshotFrame
        src="/docs-assets/screenshots/knowledge-base.png"
        alt="WebChat AI Knowledge Base Document Management"
        caption="Manage uploaded documents, inspect chunk counts, review processing status, and trigger retries."
        priority
      />

      {/* Limits Table */}
      <DocSection
        id="file-limits"
        title="File formats &amp; upload constraints"
        description="Limits enforced by the backend ingestion pipeline."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Document upload limits</caption>
            <thead>
              <tr className="border-b border-border/80 text-muted-foreground">
                <th scope="col" className="py-2.5 pr-4 font-semibold">
                  Constraint
                </th>
                <th scope="col" className="py-2.5 pr-4 font-semibold">
                  Limit
                </th>
                <th scope="col" className="py-2.5 font-semibold">
                  Details
                </th>
              </tr>
            </thead>
            <tbody>
              {LIMITS.map((row) => (
                <tr key={row.item} className="border-b border-border/50 last:border-0 align-top">
                  <td className="py-2.5 pr-4 font-medium text-foreground">{row.item}</td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-blue-600 dark:text-blue-400">
                    {row.limit}
                  </td>
                  <td className="py-2.5 text-xs text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      {/* Ingestion Pipeline Diagram */}
      <DocSection
        id="processing-pipeline"
        title="The ingestion pipeline"
        description="How files are transformed into searchable vector representations."
      >
        <DiagramBox title="Upload Processing Flow">
          <div className="grid gap-2 text-xs sm:grid-cols-3">
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <span className="font-mono text-[11px] font-bold text-blue-600 dark:text-blue-400">
                1. VALIDATION
              </span>
              <p className="mt-1 font-medium text-foreground">File &amp; Magic Bytes</p>
              <p className="mt-1 text-muted-foreground">
                Checks file extension and binary magic bytes (%PDF-, PK\x03\x04).
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <span className="font-mono text-[11px] font-bold text-blue-600 dark:text-blue-400">
                2. EXTRACTION
              </span>
              <p className="mt-1 font-medium text-foreground">Parser Extraction</p>
              <p className="mt-1 text-muted-foreground">
                pypdf for PDF, python-docx for DOCX, native utf-8 decoder for TXT/MD.
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <span className="font-mono text-[11px] font-bold text-blue-600 dark:text-blue-400">
                3. CHUNKING
              </span>
              <p className="mt-1 font-medium text-foreground">Semantic Slicing</p>
              <p className="mt-1 text-muted-foreground">
                500–800 tokens per chunk with 100-token overlap along sentence boundaries.
              </p>
            </div>
          </div>
        </DiagramBox>
      </DocSection>

      {/* Lifecycle Statuses */}
      <DocSection
        id="statuses"
        title="Document lifecycle statuses"
        description="Understand the status indicators shown on the Knowledge Base table."
      >
        <div className="flex flex-col gap-3">
          {STATUSES.map((s) => (
            <div
              key={s.status}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-border/60 p-3"
            >
              <div className="flex items-center gap-3">
                <span
                  className={`rounded font-mono text-xs px-2.5 py-0.5 font-semibold uppercase ${s.variant}`}
                >
                  {s.status}
                </span>
                <span className="text-xs text-muted-foreground">{s.description}</span>
              </div>
            </div>
          ))}
        </div>
      </DocSection>

      {/* Retrying and Deleting */}
      <DocSection
        id="management"
        title="Retrying &amp; deleting documents"
        description="How to manage knowledge over time."
      >
        <div className="flex flex-col gap-4 text-sm text-muted-foreground">
          <div>
            <p className="font-medium text-foreground flex items-center gap-2">
              <RefreshCw className="size-4 text-blue-600 dark:text-blue-400" /> Retrying a failed
              document
            </p>
            <p className="mt-1 text-xs">
              If an external embedding provider was temporarily unavailable or hit rate limits,
              click the <strong className="text-foreground">Retry</strong> button next to the
              document in the dashboard, or call:
            </p>
            <p className="mt-1 font-mono text-xs text-foreground bg-muted p-2 rounded">
              POST /api/knowledge/documents/{'{documentId}'}/retry
            </p>
          </div>

          <div>
            <p className="font-medium text-foreground flex items-center gap-2">
              <Trash2 className="size-4 text-red-600 dark:text-red-400" /> Deleting a document
            </p>
            <p className="mt-1 text-xs">
              Deleting a document permanently removes the document record, all associated vector
              chunk embeddings from the vector store, and any attached file storage. The assistant
              immediately stops referencing that material in future chats.
            </p>
          </div>
        </div>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'RAG & Retrieval Architecture',
            description: 'Learn how vector chunks are queried and cited during conversations.',
            href: '/docs/rag-pipeline',
          },
          {
            title: 'Knowledge Sources',
            description: 'Compare website crawls, document uploads, and mixed sources.',
            href: '/docs/knowledge-sources',
          },
          {
            title: 'Troubleshooting Ingestion',
            description: 'Diagnose upload rejections, corrupted files, and processing errors.',
            href: '/docs/troubleshooting',
          },
        ]}
      />
    </div>
  );
}

/**
 * Website domain types mirrored from the backend API (docs/05-Backend-Schema.md §5-6).
 */

export type WebsiteStatus = 'pending' | 'crawling' | 'processing' | 'ready' | 'failed';

export type KnowledgeStatus = 'none' | 'processing' | 'ready' | 'failed';

export type SourceMode = 'website' | 'files' | 'mixed';

export interface Website {
  id: string;
  tenant_id: string;
  name: string;
  url: string | null;
  source_mode?: SourceMode;
  status: WebsiteStatus;
  pages_indexed: number;
  last_crawled_at: string | null;
  checksum: string | null;
  created_at: string;
  updated_at: string;
  widget_id: string;
  /** Phase 5 knowledge base statistics (docs/06, ADR-008). */
  knowledge_status: KnowledgeStatus;
  knowledge_documents: number;
  knowledge_chunks: number;
  last_knowledge_at: string | null;
  /** Open Graph / Twitter preview image URL surfaced on the website card. */
  preview_image?: string | null;
}

export interface Widget {
  widget_id: string;
  website_id: string;
  theme: string;
  position: string;
  primary_color: string;
  accent_color: string;
  font_size: string;
  logo_url: string | null;
  avatar_url: string | null;
  welcome_message: string;
  placeholder: string;
  suggested_questions: string[];
  branding: boolean;
  dark_mode: boolean;
  auto_open: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateWebsiteResponse {
  website: Website;
  widget: Widget;
  embed_script: string;
}

export interface WidgetResponse {
  widget: Widget;
  embed_script: string;
}

export interface CreateWebsiteInput {
  name: string;
  url?: string | null;
  source_mode?: SourceMode;
}

export interface UpdateWebsiteInput {
  websiteId: string;
  name?: string;
  url?: string | null;
  source_mode?: SourceMode;
}

export type CrawlJobStatus = 'pending' | 'running' | 'processing' | 'completed' | 'failed';

export interface CrawlJobError {
  url: string;
  message: string;
  /** Egress-hardening classification (target_blocked, target_rate_limited, ...). */
  classification?: string | null;
  status_code?: number | null;
  method?: string | null;
  attempt?: number | null;
}

export interface CrawlJob {
  id: string;
  website_id: string;
  status: CrawlJobStatus;
  pages_total: number;
  pages_completed: number;
  errors: CrawlJobError[];
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface StartCrawlResponse {
  crawl_job_id: string;
  website_id: string;
  status: CrawlJobStatus;
  created_at: string;
}

/** Real-time crawl progress event from SSE stream. */
export interface CrawlProgressEvent {
  status: CrawlJobStatus | 'started' | 'fetching' | 'extracting' | 'embedding';
  message?: string;
  current_url?: string;
  pages_completed?: number;
  pages_total?: number;
  pages?: number;
  chunks?: number;
  error?: string;
}

/**
 * A chatbot is chat-ready only when its knowledge-base embedding has finished.
 * For 'files' mode chatbots, no website crawl is required; readiness depends on
 * knowledge_status === 'ready' and non-zero chunks.
 * For 'website' and 'mixed' modes, both the website crawl and knowledge-base
 * embedding must have finished (status === 'ready' && knowledge_status === 'ready').
 */
export function isChatReady(
  website: Pick<Website, 'status' | 'knowledge_status'> & {
    source_mode?: SourceMode;
    knowledge_chunks?: number;
  },
): boolean {
  if (website.source_mode === 'files') {
    return (
      website.status !== 'failed' &&
      website.knowledge_status === 'ready' &&
      (website.knowledge_chunks === undefined || website.knowledge_chunks > 0)
    );
  }
  return website.status === 'ready' && website.knowledge_status === 'ready';
}

/**
 * True while the knowledge base is still being embedded.
 * For 'files' mode: knowledge_status === 'processing'.
 * For 'website' / 'mixed': crawl is complete but knowledge is embedding (status 'ready' + knowledge_status 'processing').
 */
export function isEmbeddingInProgress(
  website: Pick<Website, 'status' | 'knowledge_status'> & {
    source_mode?: SourceMode;
  },
): boolean {
  if (website.source_mode === 'files') {
    return website.status !== 'failed' && website.knowledge_status === 'processing';
  }
  return website.status === 'ready' && website.knowledge_status === 'processing';
}

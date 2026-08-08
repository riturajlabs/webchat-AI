/**
 * Website domain types mirrored from the backend API (docs/05-Backend-Schema.md §5-6).
 */

export type WebsiteStatus = 'pending' | 'crawling' | 'processing' | 'ready' | 'failed';

export interface Website {
  id: string;
  tenant_id: string;
  name: string;
  url: string;
  status: WebsiteStatus;
  pages_indexed: number;
  last_crawled_at: string | null;
  checksum: string | null;
  created_at: string;
  updated_at: string;
  widget_id: string;
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
  /** One-time widget secret; only a hash is stored server-side (ADR-004). */
  widget_secret: string;
  embed_script: string;
}

export interface UpdateWebsiteInput {
  websiteId: string;
  name?: string;
  url?: string;
}

export type CrawlJobStatus = 'pending' | 'running' | 'processing' | 'completed' | 'failed';

export interface CrawlJobError {
  url: string;
  message: string;
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

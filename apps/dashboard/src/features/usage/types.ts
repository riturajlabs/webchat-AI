/**
 * Billing/usage domain types mirrored from the backend API (Phase 13).
 */

export interface PlanLimits {
  max_websites: number | null;
  max_monthly_messages: number | null;
  max_monthly_tokens: number | null;
  max_documents: number | null;
  max_crawl_pages: number | null;
}

export interface Plan {
  id: string;
  name: string;
  description: string;
  limits: PlanLimits;
  /** Self-serve list price in minor units (Phase 14); null/0 = not purchasable. */
  price_cents?: number | null;
  /** ISO 4217 currency of `price_cents`. */
  currency?: string;
}

export interface UsageCounts {
  messages_sent: number;
  ai_responses: number;
  tokens_used: number;
  documents_created: number;
  crawl_pages: number;
  websites: number;
  documents: number;
}

/** One limit row: used vs cap plus utilization percentage (null = unlimited). */
export interface UsageMetric {
  metric: string;
  used: number;
  limit: number | null;
  percent: number | null;
}

export interface Usage {
  plan: Plan;
  usage: UsageCounts;
  limits: UsageMetric[];
}

export const USAGE_LIMIT_LABELS: Record<string, string> = {
  messages_sent: 'Messages',
  websites: 'Websites',
  tokens_used: 'Tokens',
  documents: 'Documents',
  crawl_pages: 'Crawl pages',
};

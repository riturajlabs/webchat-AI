/**
 * Admin domain types mirrored from backend/schemas/admin.py (ADR-006).
 * The admin surface reuses the existing collections; these types only add
 * platform-wide fields (tenant_id on crawl jobs, counts on tenant detail).
 */

export interface AdminTenant {
  id: string;
  company_name: string;
  plan: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AdminTenantUsage {
  conversations: number;
  messages: number;
  input_tokens: number;
  output_tokens: number;
}

export interface AdminTenantDetail extends AdminTenant {
  website_count: number;
  user_count: number;
  active_crawl_jobs: number;
  usage: AdminTenantUsage;
}

export interface AdminTenantListResponse {
  items: AdminTenant[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: string;
  status: string;
  email_verified: boolean;
  tenant_id: string;
  last_login: string | null;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminStats {
  tenants: { total: number; active: number; suspended: number };
  users: { total: number; active: number; suspended: number };
  usage: {
    conversations: number;
    messages: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
  crawl_jobs: { total: number; active: number; failed: number; error_rate: number };
}

export interface AdminCrawlJob {
  id: string;
  tenant_id: string;
  website_id: string;
  status: string;
  pages_total: number;
  pages_completed: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminCrawlJobListResponse {
  items: AdminCrawlJob[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminAuditLog {
  id: string;
  tenant_id: string | null;
  user_id: string | null;
  action: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AdminAuditLogListResponse {
  items: AdminAuditLog[];
  total: number;
  page: number;
  per_page: number;
}

/** Per-collection row counts (`/api/admin/overview`, `/api/admin/system-health`). */
export interface AdminSystemCounts {
  users: number;
  tenants: number;
  websites: number;
  widgets: number;
  documents: number;
  chat_sessions: number;
  messages: number;
  usage_records: number;
  api_keys: number;
  subscriptions: number;
  audit_logs: number;
  admin_audit_logs: number;
}

/** Dashboard overview (`/api/admin/overview`, Phase 15). */
export interface AdminOverview {
  stats: AdminStats;
  counts: AdminSystemCounts;
  active_subscriptions: number;
  total_revenue_cents: number;
  currency: string;
}

/** A payment-history row (`/api/admin/revenue`, Phase 15). */
export interface AdminSubscription {
  id: string;
  tenant_id: string;
  plan_id: string;
  status: string;
  payment_provider: string | null;
  payment_id: string | null;
  start_date: string;
  end_date: string | null;
  amount_cents: number | null;
  currency: string | null;
  created_at: string;
}

/** One calendar month of collected revenue (Phase 15). */
export interface AdminRevenuePeriod {
  period: string;
  revenue_cents: number;
  payments: number;
}

export interface AdminRevenueReport {
  total_revenue_cents: number;
  paid_payments: number;
  active_subscriptions: number;
  currency: string;
  periods: AdminRevenuePeriod[];
  recent_payments: AdminSubscription[];
}

export interface AdminCheck {
  name: string;
  status: 'ok' | 'degraded';
}

/** System health (`/api/admin/system-health`, Phase 15). */
export interface AdminSystemHealth {
  status: string;
  checks: AdminCheck[];
  counts: AdminSystemCounts;
  checked_at: string;
}

/** A platform operator action on the dedicated admin trail (`/api/admin/audit`). */
export interface AdminAdminAuditLog {
  id: string;
  actor_user_id: string | null;
  action: string;
  tenant_id: string | null;
  user_id: string | null;
  plan_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AdminAdminAuditLogListResponse {
  items: AdminAdminAuditLog[];
  total: number;
  page: number;
  per_page: number;
}

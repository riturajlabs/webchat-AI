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

/**
 * API key domain types mirrored from the backend API (docs/05-Backend-Schema.md §12).
 */

export interface ApiKey {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  status: 'active' | 'revoked';
  last_used_at: string | null;
  created_at: string;
}

export interface CreateApiKeyResponse {
  /** Full raw secret; shown exactly once and never stored server-side (ADR-004). */
  api_key: string;
  key: ApiKey;
}

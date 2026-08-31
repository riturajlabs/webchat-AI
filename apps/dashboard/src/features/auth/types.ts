/** Auth domain types mirrored from backend/schemas/auth.py (ADR-003). */

export interface UserOut {
  id: string;
  name: string;
  email: string;
  role: string;
  email_verified: boolean;
  status: string;
  tenant_id: string;
  created_at: string;
  avatar_url?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  csrf_token: string;
  user: UserOut;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

export interface MessageResponse {
  message: string;
}

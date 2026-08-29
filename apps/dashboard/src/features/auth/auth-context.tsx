'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { api } from '@/lib/api';
import {
  clearSession,
  getAccessToken,
  hasSessionCookie,
  setAccessToken,
  setCsrfToken,
} from '@/lib/session';

import type { AuthResponse, MessageResponse, RefreshResponse, UserOut } from './types';

type AuthStatus = 'loading' | 'ready';

interface AuthContextValue {
  user: UserOut | null;
  status: AuthStatus;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<UserOut>;
  register: (name: string, email: string, password: string) => Promise<UserOut>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  const refreshSession = useCallback(async () => {
    try {
      const response = await api.post<RefreshResponse>('/api/auth/refresh');
      setAccessToken(response.access_token);
      setUser(response.user);
      return true;
    } catch {
      setUser(null);
      return false;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      if (getAccessToken()) {
        try {
          const current = await api.get<UserOut>('/api/auth/me');
          if (!cancelled) {
            setUser(current);
            setStatus('ready');
            return;
          }
        } catch {
          // The API client already performed a single silent refresh on a 401
          // and clears the session + redirects to /login when that refresh
          // fails. Never trigger a second refresh here (R1).
        }
      } else if (hasSessionCookie()) {
        // No in-memory token but the session cookies exist: restore the
        // session from the httpOnly refresh cookie. refreshSession sets the
        // user on success and clears nothing on failure, so the status is
        // finalized here either way. Single refresh attempt, and anonymous
        // visitors (no session cookie) skip the network call entirely (NET-1).
        await refreshSession();
      }

      if (!cancelled) {
        setStatus('ready');
      }
    }

    void init();
    return () => {
      cancelled = true;
    };
  }, [refreshSession]);

  const login = useCallback(async (email: string, password: string): Promise<UserOut> => {
    const response = await api.post<AuthResponse>('/api/auth/login', { email, password });
    setAccessToken(response.access_token);
    setCsrfToken(response.csrf_token);
    setUser(response.user);
    return response.user;
  }, []);

  const register = useCallback(
    async (name: string, email: string, password: string): Promise<UserOut> => {
      const response = await api.post<AuthResponse>('/api/auth/register', {
        name,
        email,
        password,
      });
      setAccessToken(response.access_token);
      setCsrfToken(response.csrf_token);
      setUser(response.user);
      return response.user;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.post<MessageResponse>('/api/auth/logout');
    } finally {
      clearSession();
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: user !== null,
      login,
      register,
      logout,
      refreshSession,
    }),
    [user, status, login, register, logout, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider.');
  }
  return context;
}

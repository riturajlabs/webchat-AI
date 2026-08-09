import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  clearSession,
  getAccessToken,
  getCsrfToken,
  setAccessToken,
  setCsrfToken,
} from './session';

describe('session', () => {
  beforeEach(() => {
    clearSession();
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    clearSession();
  });

  it('stores access and CSRF tokens in memory only', () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-1');

    expect(getAccessToken()).toBe('access-1');
    expect(getCsrfToken()).toBe('csrf-1');
  });

  it('never writes tokens to localStorage or sessionStorage (ADR-003)', () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-1');

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('returns null before any token is set', () => {
    expect(getAccessToken()).toBeNull();
    expect(getCsrfToken()).toBeNull();
  });

  it('clears both tokens', () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-1');
    clearSession();

    expect(getAccessToken()).toBeNull();
    expect(getCsrfToken()).toBeNull();
  });
});

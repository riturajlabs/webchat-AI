import { describe, expect, it } from 'vitest';
import { VISITOR_COOKIE_NAME, getVisitorId, type CookieAccessor } from './visitor';

function fakeCookieAccessor(): CookieAccessor & { cookies: Map<string, string> } {
  const cookies = new Map<string, string>();
  return {
    cookies,
    read(name: string) {
      return cookies.get(name) ?? null;
    },
    write(name: string, value: string) {
      cookies.set(name, value);
    },
  };
}

describe('getVisitorId', () => {
  it('writes the anonymous cookie once on first use', () => {
    const accessor = fakeCookieAccessor();
    const id = getVisitorId(accessor);
    expect(id).toBeTruthy();
    expect(accessor.read(VISITOR_COOKIE_NAME)).toBe(id);
  });

  it('returns the same id across "reloads" via the cookie', () => {
    const accessor = fakeCookieAccessor();
    const first = getVisitorId(accessor);
    const second = getVisitorId(accessor);
    expect(second).toBe(first);
  });

  it('falls back to an in-memory id when cookies are unavailable', () => {
    const accessor: CookieAccessor = {
      read: () => null,
      write: () => {
        throw new Error('cookies blocked');
      },
    };
    const first = getVisitorId(accessor);
    const second = getVisitorId(accessor);
    expect(first).toBeTruthy();
    expect(second).toBe(first);
  });

  it('never touches localStorage or sessionStorage', () => {
    const storageSpy = {
      getItem: () => {
        throw new Error('storage must not be used');
      },
      setItem: () => {
        throw new Error('storage must not be used');
      },
    };
    const originalLocal = globalThis.localStorage;
    const originalSession = globalThis.sessionStorage;
    Object.defineProperty(globalThis, 'localStorage', { value: storageSpy });
    Object.defineProperty(globalThis, 'sessionStorage', { value: storageSpy });
    try {
      const accessor = fakeCookieAccessor();
      expect(() => getVisitorId(accessor)).not.toThrow();
    } finally {
      Object.defineProperty(globalThis, 'localStorage', { value: originalLocal });
      Object.defineProperty(globalThis, 'sessionStorage', { value: originalSession });
    }
  });
});

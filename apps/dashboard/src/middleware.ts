import { NextResponse, type NextRequest } from 'next/server';

/**
 * Early authentication protection for dashboard routes.
 *
 * This is a presence check only: it bounces requests that cannot possibly
 * have a session before any dashboard JavaScript runs. The authoritative
 * check remains the client-side AuthGuard (silent refresh against the API),
 * which this middleware complements rather than replaces.
 *
 * Cookie notes: the backend issues the httpOnly refresh token with
 * `path=/api/auth`, so page navigations never carry it. The CSRF cookie is
 * issued alongside it at `path=/` and cleared together with it, so either
 * being present indicates a live browser session. Both names follow the
 * backend defaults (`REFRESH_COOKIE_NAME` / `CSRF_COOKIE_NAME`).
 */
const REFRESH_COOKIE = process.env.NEXT_PUBLIC_REFRESH_COOKIE_NAME ?? 'refresh_token';
const CSRF_COOKIE = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? 'csrf_token';

/** Top-level paths served by the (dashboard) route group. */
const PROTECTED_PREFIXES = [
  '/dashboard',
  '/websites',
  '/knowledge',
  '/conversations',
  '/analytics',
  '/usage',
  '/billing',
  '/widget',
  '/widget-test',
  '/api-keys',
  '/profile',
  '/settings',
  '/admin',
];

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(
    request.cookies.get(REFRESH_COOKIE)?.value ?? request.cookies.get(CSRF_COOKIE)?.value,
  );
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (!isProtectedPath(pathname) || hasSessionCookie(request)) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = '/login';
  loginUrl.search = '';
  loginUrl.searchParams.set('redirect', encodeURIComponent(pathname + search));
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    '/dashboard/:path*',
    '/websites/:path*',
    '/knowledge/:path*',
    '/conversations/:path*',
    '/analytics/:path*',
    '/usage/:path*',
    '/billing/:path*',
    '/widget/:path*',
    '/widget-test/:path*',
    '/api-keys/:path*',
    '/profile/:path*',
    '/settings/:path*',
    '/admin/:path*',
  ],
};

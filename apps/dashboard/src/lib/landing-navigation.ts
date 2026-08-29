/**
 * Auth-aware destination resolution for the marketing landing page.
 *
 * The landing page is public, but its CTAs must never send an already
 * authenticated user back through sign-in/sign-up. Each action resolves to a
 * route based on the current auth state, reusing only the existing app routes
 * (/dashboard, /billing, /signup, /login, /docs, /).
 *
 * The `useAuth` state is supplied by the caller so this module stays a pure
 * helper and does not couple itself to the React context.
 */

export type LandingAction =
  | 'sign-in'
  | 'get-started'
  | 'start-free'
  | 'pricing-plan'
  | 'contact-sales'
  | 'dashboard'
  | 'docs';

const LANDING_DESTINATIONS: Record<LandingAction, { protected: string; auth: string }> = {
  'sign-in': { protected: '/login', auth: '/dashboard' },
  'get-started': { protected: '/signup', auth: '/dashboard' },
  'start-free': { protected: '/signup', auth: '/dashboard' },
  'pricing-plan': { protected: '/signup', auth: '/billing' },
  'contact-sales': { protected: '/signup', auth: '/billing' },
  dashboard: { protected: '/signup', auth: '/dashboard' },
  docs: { protected: '/docs', auth: '/docs' },
};

export function getLandingDestination(action: LandingAction, isAuthenticated: boolean): string {
  const entry = LANDING_DESTINATIONS[action];
  return isAuthenticated ? entry.auth : entry.protected;
}

/**
 * Subscription/payment domain types mirrored from the backend API (Phase 14).
 */

export interface SubscriptionOut {
  id: string;
  plan_id: string;
  plan_name: string;
  status: 'active' | 'trialing' | 'cancelled' | 'expired' | string;
  payment_provider: string | null;
  payment_id: string | null;
  start_date: string;
  end_date: string | null;
  created_at: string;
}

export interface PaymentOut {
  id: string;
  plan_id: string;
  plan_name: string;
  status: string;
  amount_cents: number | null;
  currency: string;
  payment_provider: string | null;
  payment_id: string | null;
  created_at: string;
}

export interface SubscriptionReport {
  subscription: SubscriptionOut | null;
  payments: PaymentOut[];
}

export interface CheckoutRequest {
  plan_id: string;
  success_url: string;
  cancel_url: string;
}

export interface Checkout {
  checkout_id: string;
  url: string;
}

export const SUBSCRIPTION_STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  trialing: 'Trial',
  cancelled: 'Cancelled',
  expired: 'Expired',
};

export function formatPrice(amountCents: number | null, currency: string): string {
  if (amountCents === null || amountCents === undefined) {
    return 'Custom';
  }
  const formatter = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    currencyDisplay: 'narrowSymbol',
  });
  return formatter.format(amountCents / 100);
}

/** ISO date string → localized date (e.g. "Aug 11, 2026"). Falls back to em-dash. */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}

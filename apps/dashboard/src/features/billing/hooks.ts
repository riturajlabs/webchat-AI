/**
 * React Query hooks for the subscription/payment feature (Phase 14,
 * 00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { Checkout, CheckoutRequest, SubscriptionReport } from './types';

export const billingKeys = {
  all: ['billing'] as const,
  subscription: ['billing', 'subscription'] as const,
};

export function useSubscriptionReport() {
  return useQuery({
    queryKey: billingKeys.subscription,
    queryFn: () => api.get<SubscriptionReport>('/api/billing/subscription'),
  });
}

export function useCreateCheckout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CheckoutRequest) => api.post<Checkout>('/api/billing/checkout', input),
    onSuccess: (checkout) => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.subscription });
      window.location.assign(checkout.url);
    },
  });
}

/**
 * React Query hooks for the billing/usage feature (Phase 13,
 * 00-AI-Development-Rules §14).
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { Plan, Usage } from './types';

export const usageKeys = {
  all: ['usage'] as const,
  usage: ['usage', 'current'] as const,
  plans: ['usage', 'plans'] as const,
};

export function useUsage() {
  return useQuery({
    queryKey: usageKeys.usage,
    queryFn: () => api.get<Usage>('/api/billing/usage'),
  });
}

export function usePlans() {
  return useQuery({
    queryKey: usageKeys.plans,
    queryFn: () => api.get<Plan[]>('/api/billing/plans'),
  });
}

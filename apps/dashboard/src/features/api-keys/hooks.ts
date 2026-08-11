/**
 * React Query hooks for the API keys feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { ApiKey, CreateApiKeyResponse } from './types';

export const apiKeysKeys = {
  all: ['api-keys'] as const,
};

export function useApiKeys() {
  return useQuery({
    queryKey: apiKeysKeys.all,
    queryFn: () => api.get<ApiKey[]>('/api/api-keys'),
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string }) => api.post<CreateApiKeyResponse>('/api/api-keys', input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKeysKeys.all });
    },
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => api.delete<void>(`/api/api-keys/${keyId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKeysKeys.all });
    },
  });
}

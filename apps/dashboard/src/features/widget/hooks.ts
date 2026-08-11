/**
 * React Query hooks for the widget builder (Phase 11.5).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type { UpdateWidgetConfigInput, WidgetResponse } from './types';

export const widgetKeys = {
  config: (websiteId: string) => ['widget-config', websiteId] as const,
};

export function useWidgetConfig(websiteId: string | null) {
  return useQuery({
    queryKey: widgetKeys.config(websiteId ?? ''),
    queryFn: () => api.get<WidgetResponse>(`/api/websites/${websiteId}/widget`),
    enabled: websiteId !== null,
  });
}

export function useUpdateWidgetConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ websiteId, changes }: UpdateWidgetConfigInput) =>
      api.patch<WidgetResponse>(`/api/websites/${websiteId}/widget`, changes),
    onSuccess: (data, variables) => {
      void queryClient.invalidateQueries({ queryKey: widgetKeys.config(variables.websiteId) });
    },
  });
}

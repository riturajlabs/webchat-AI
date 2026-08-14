/**
 * React Query hooks for the widget builder (Phase 11.5).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE_URL } from '@/lib/api';

import type { UpdateWidgetConfigInput, WidgetResponse } from './types';
import { fetchPublicConfig } from './widget-test';

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

/**
 * Live check of the public widget config endpoint from the dashboard origin.
 *
 * The browser sends `Origin: <dashboard origin>` on this cross-origin request,
 * so the result doubles as a real-time probe of the backend origin guard (see
 * `fetchPublicConfig`).
 */
export function useWidgetPublicStatus(widgetId: string | null) {
  return useQuery({
    queryKey: ['widget-public-status', widgetId ?? ''],
    queryFn: () => fetchPublicConfig(API_BASE_URL, widgetId ?? ''),
    enabled: widgetId !== null,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

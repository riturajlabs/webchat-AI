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
 * The probe must be CROSS-ORIGIN for the browser to send an `Origin` header:
 * a widget API base URL that resolves to the dashboard's own origin (the
 * same-origin proxy kept for the authenticated API client) makes the browser
 * omit `Origin` on GETs, so the backend — correctly — answers
 * `WIDGET_ORIGIN_NOT_ALLOWED` ("a valid Origin header is required"). The
 * widget's real API base (the embed script's `data-api-base-url`) is the
 * backend origin, so probing it lets the browser send
 * `Origin: <dashboard origin>`, which the configured dashboard-origin
 * allowlist permits. `apiBaseUrl` defaults to `API_BASE_URL` for local
 * development, where the dashboard already calls the backend cross-origin.
 */
export function useWidgetPublicStatus(widgetId: string | null, apiBaseUrl: string | null) {
  return useQuery({
    queryKey: ['widget-public-status', widgetId ?? '', apiBaseUrl ?? ''],
    queryFn: () => fetchPublicConfig(apiBaseUrl ?? API_BASE_URL, widgetId ?? ''),
    enabled: widgetId !== null && apiBaseUrl !== null,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

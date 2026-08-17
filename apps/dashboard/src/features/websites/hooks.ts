/**
 * React Query hooks for the websites feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, useCallback } from 'react';

import { api } from '@/lib/api';

import type {
  CrawlJob,
  CrawlProgressEvent,
  CreateWebsiteResponse,
  StartCrawlResponse,
  UpdateWebsiteInput,
  Website,
  WidgetResponse,
} from './types';

export const websitesKeys = {
  all: ['websites'] as const,
};

export const crawlJobKeys = {
  detail: (jobId: string) => ['crawl-job', jobId] as const,
};

const TERMINAL_CRAWL_STATUSES = new Set(['completed', 'failed']);

export function useWebsites() {
  return useQuery({
    queryKey: websitesKeys.all,
    queryFn: () => api.get<Website[]>('/api/websites'),
  });
}

export function useCreateWebsite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; url: string }) =>
      api.post<CreateWebsiteResponse>('/api/websites', input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    },
  });
}

export function useUpdateWebsite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ websiteId, ...input }: UpdateWebsiteInput) =>
      api.patch<Website>(`/api/websites/${websiteId}`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    },
  });
}

export function useDeleteWebsite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (websiteId: string) => api.delete<void>(`/api/websites/${websiteId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    },
  });
}

export function useStartCrawl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (websiteId: string) =>
      api.post<StartCrawlResponse>(`/api/websites/${websiteId}/crawl`),
    onSuccess: (data) => {
      queryClient.setQueryData(crawlJobKeys.detail(data.crawl_job_id), data);
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    },
  });
}

export function useCrawlJob(jobId: string | null) {
  return useQuery({
    queryKey: crawlJobKeys.detail(jobId ?? ''),
    queryFn: () => api.get<CrawlJob>(`/api/crawl-jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) =>
      TERMINAL_CRAWL_STATUSES.has(query.state.data?.status ?? '') ? false : 3000,
  });
}

/**
 * SSE-based real-time crawl progress hook.
 *
 * Connects to `GET /api/crawl-jobs/{jobId}/stream` for live events.
 * Falls back gracefully: if SSE fails, the caller still has the polling
 * `useCrawlJob` hook as a safety net.
 */
export function useCrawlProgress(jobId: string | null) {
  const [progress, setProgress] = useState<CrawlProgressEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnected(false);
  }, []);

  useEffect(() => {
    if (!jobId) {
      disconnect();
      return;
    }

    const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const url = `${baseUrl}/api/crawl-jobs/${jobId}/stream`;

    // EventSource only supports GET with cookies; we need the auth cookie.
    // Use fetch + ReadableStream for POST-style SSE, but since this is GET,
    // EventSource works with cookies (same-origin or with credentials).
    const es = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);

    es.addEventListener('crawl.snapshot', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore parse errors */
      }
    }) as EventListener);

    es.addEventListener('crawl.started', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore */
      }
    }) as EventListener);

    es.addEventListener('crawl.progress', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore */
      }
    }) as EventListener);

    es.addEventListener('crawl.fetching', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore */
      }
    }) as EventListener);

    es.addEventListener('crawl.completed', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore */
      }
      disconnect();
    }) as EventListener);

    es.addEventListener('crawl.failed', ((e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as CrawlProgressEvent;
        setProgress(data);
      } catch {
        /* ignore */
      }
      disconnect();
    }) as EventListener);

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects; let it do so
    };

    return disconnect;
  }, [jobId, disconnect]);

  return { progress, connected };
}

export function useWebsiteWidget(websiteId: string | null) {
  return useQuery({
    queryKey: ['website-widget', websiteId ?? ''],
    queryFn: () => api.get<WidgetResponse>(`/api/websites/${websiteId}/widget`),
    enabled: websiteId !== null,
  });
}

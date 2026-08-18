/**
 * React Query hooks for the websites feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, useCallback } from 'react';

import { API_BASE_URL, api } from '@/lib/api';

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

const SSE_BASE_DELAY_MS = 2_000;
const SSE_MAX_RETRIES = 3;

/**
 * SSE-based real-time crawl progress hook.
 *
 * Connects to `GET /api/crawl-jobs/{jobId}/stream` for live events.
 * Falls back gracefully: if SSE fails, the caller still has the polling
 * `useCrawlJob` hook as a safety net.
 *
 * Reconnection uses controlled exponential backoff instead of relying on
 * EventSource's built-in auto-reconnect.  After `SSE_MAX_RETRIES`
 * consecutive failures the connection is permanently closed for this
 * crawl job and the UI falls back to polling.
 */
export function useCrawlProgress(jobId: string | null) {
  const [progress, setProgress] = useState<CrawlProgressEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountRef = useRef(0);
  const mountedRef = useRef(true);

  const cleanup = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnected(false);
    setReconnecting(false);
  }, []);

  const connect = useCallback(
    (url: string) => {
      const es = new EventSource(url, { withCredentials: true });
      eventSourceRef.current = es;

      es.onopen = () => {
        if (!mountedRef.current) return;
        retryCountRef.current = 0;
        setConnected(true);
        setReconnecting(false);
      };

      const handleProgressEvent = ((e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as CrawlProgressEvent;
          setProgress(data);
        } catch {
          /* ignore parse errors */
        }
      }) as EventListener;

      for (const eventType of [
        'crawl.snapshot',
        'crawl.started',
        'crawl.progress',
        'crawl.fetching',
      ]) {
        es.addEventListener(eventType, handleProgressEvent);
      }

      es.addEventListener('crawl.completed', ((e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as CrawlProgressEvent;
          setProgress(data);
        } catch {
          /* ignore */
        }
        cleanup();
      }) as EventListener);

      es.addEventListener('crawl.failed', ((e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as CrawlProgressEvent;
          setProgress(data);
        } catch {
          /* ignore */
        }
        cleanup();
      }) as EventListener);

      es.onerror = () => {
        if (!mountedRef.current) return;
        setConnected(false);

        es.close();
        eventSourceRef.current = null;

        const attempt = retryCountRef.current;
        if (attempt >= SSE_MAX_RETRIES) {
          setReconnecting(false);
          return;
        }

        retryCountRef.current = attempt + 1;
        setReconnecting(true);

        const delay = SSE_BASE_DELAY_MS * 2 ** attempt;
        retryTimerRef.current = setTimeout(() => {
          retryTimerRef.current = null;
          if (!mountedRef.current) return;
          connect(url);
        }, delay);
      };
    },
    [cleanup],
  );

  useEffect(() => {
    mountedRef.current = true;

    if (!jobId) {
      cleanup();
      return;
    }

    const url = `${API_BASE_URL}/api/crawl-jobs/${jobId}/stream`;

    retryCountRef.current = 0;
    connect(url);

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [jobId, connect, cleanup]);

  return { progress, connected, reconnecting };
}

export function useWebsiteWidget(websiteId: string | null) {
  return useQuery({
    queryKey: ['website-widget', websiteId ?? ''],
    queryFn: () => api.get<WidgetResponse>(`/api/websites/${websiteId}/widget`),
    enabled: websiteId !== null,
  });
}

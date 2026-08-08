/**
 * React Query hooks for the websites feature (00-AI-Development-Rules §14).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type {
  CrawlJob,
  CreateWebsiteResponse,
  StartCrawlResponse,
  UpdateWebsiteInput,
  Website,
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

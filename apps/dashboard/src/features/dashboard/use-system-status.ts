import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface SystemStatus {
  status: string;
  checks: {
    database: boolean;
    redis: boolean;
  };
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.get<SystemStatus>('/api/health'),
    refetchInterval: 60_000,
  });
}

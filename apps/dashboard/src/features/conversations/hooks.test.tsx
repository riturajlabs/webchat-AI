import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';

import {
  CONVERSATION_ACTIVE_REFRESH_MS,
  CONVERSATIONS_LIST_REFRESH_MS,
  useConversation,
  useConversations,
} from './hooks';
import type { ConversationDetail, ConversationListResponse } from './types';

vi.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  api: {
    get: vi.fn(() => Promise.reject(new Error('api.get not mocked'))),
    post: vi.fn(() => Promise.resolve(undefined)),
  },
}));

const LIST: ConversationListResponse = {
  items: [
    {
      id: 'conv-1',
      website_id: 'site-1',
      visitor_id: 'visitor-1',
      title: 'Help with pricing',
      message_count: 2,
      last_message: 'How much is Pro?',
      status: 'awaiting',
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
  ],
  total: 1,
  page: 1,
  per_page: 20,
};

function detail(status: ConversationDetail['status']): ConversationDetail {
  return {
    id: 'conv-1',
    website_id: 'site-1',
    visitor_id: 'visitor-1',
    title: 'Help with pricing',
    status,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    messages: [
      {
        role: 'user',
        content: 'How much is Pro?',
        sources: [],
        response_time: null,
        input_tokens: 5,
        output_tokens: 0,
        created_at: '2026-08-01T00:00:00Z',
      },
    ],
  };
}

describe('useConversations', () => {
  const mockedGetApi = vi.mocked(api.get);
  let queryClient: QueryClient;

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockedGetApi.mockImplementation((path: string) => {
      if (path === '/api/conversations?page=1&per_page=20') return Promise.resolve(LIST);
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('refreshes the list on the poll interval while mounted', async () => {
    const { result, unmount } = renderHook(() => useConversations({ page: 1, perPage: 20 }), {
      wrapper: Wrapper,
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toEqual(LIST);
    const calls = mockedGetApi.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATIONS_LIST_REFRESH_MS + 1);
    });
    expect(mockedGetApi.mock.calls.length).toBe(calls + 1);
    expect(result.current.data).toEqual(LIST);

    unmount();
  });

  it('stops polling the list once the mount is gone', async () => {
    const { unmount } = renderHook(() => useConversations({ page: 1, perPage: 20 }), {
      wrapper: Wrapper,
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const calls = mockedGetApi.mock.calls.length;

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATIONS_LIST_REFRESH_MS * 3);
    });
    expect(mockedGetApi.mock.calls.length).toBe(calls);
  });
});

describe('useConversation', () => {
  const mockedGetApi = vi.mocked(api.get);
  let queryClient: QueryClient;

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('polls while the reply is still being generated (awaiting)', async () => {
    mockedGetApi.mockImplementation((path: string) => {
      if (path === '/api/conversations/conv-1') return Promise.resolve(detail('awaiting'));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const { result, unmount } = renderHook(() => useConversation('conv-1'), { wrapper: Wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe('awaiting');
    const calls = mockedGetApi.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS + 1);
    });
    expect(mockedGetApi.mock.calls.length).toBe(calls + 1);

    unmount();
  });

  it('stops polling once the conversation is answered', async () => {
    mockedGetApi.mockImplementation((path: string) => {
      if (path === '/api/conversations/conv-1') return Promise.resolve(detail('awaiting'));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const { result, unmount } = renderHook(() => useConversation('conv-1'), { wrapper: Wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // The reply lands: the next poll sees 'answered' and disables polling.
    mockedGetApi.mockImplementation((path: string) => {
      if (path === '/api/conversations/conv-1') return Promise.resolve(detail('answered'));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS + 1);
    });
    expect(result.current.data?.status).toBe('answered');
    const callsAfterAnswer = mockedGetApi.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS * 3);
    });
    expect(mockedGetApi.mock.calls.length).toBe(callsAfterAnswer);

    unmount();
  });

  it('does not re-poll when a poll fails', async () => {
    mockedGetApi
      .mockResolvedValueOnce(detail('awaiting'))
      .mockRejectedValueOnce(new Error('network down'));

    const { result, unmount } = renderHook(() => useConversation('conv-1'), { wrapper: Wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS + 1);
    });
    expect(result.current.data?.status).toBe('awaiting');
    const callsAfterError = mockedGetApi.mock.calls.length;

    // retry: false + no refetchOnError -> a failed poll does not start a
    // retry loop: the next tick only happens on the normal interval.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS + 1);
    });
    expect(mockedGetApi.mock.calls.length).toBe(callsAfterError + 1);

    unmount();
  });

  it('stops polling after a failed state even if the query is re-observed', async () => {
    mockedGetApi.mockImplementation((path: string) => {
      if (path === '/api/conversations/conv-1') return Promise.resolve(detail('failed'));
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });

    const { result, unmount } = renderHook(() => useConversation('conv-1'), {
      wrapper: Wrapper,
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe('failed');
    const calls = mockedGetApi.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONVERSATION_ACTIVE_REFRESH_MS * 3);
    });
    expect(mockedGetApi.mock.calls.length).toBe(calls);

    unmount();
  });
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';

import { ConversationDetailPage } from './conversation-detail';
import { ConversationsPage } from './conversations-page';
import { useConversation, useConversations, useDeleteConversation } from './hooks';
import type { ConversationDetail, ConversationListResponse, ConversationSummary } from './types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useConversations: vi.fn(),
  useConversation: vi.fn(),
  useDeleteConversation: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { useWebsites } from '@/features/websites/hooks';

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedUseConversations = vi.mocked(useConversations);
const mockedUseConversation = vi.mocked(useConversation);
const mockedUseDeleteConversation = vi.mocked(useDeleteConversation);
const mockedUseRouter = vi.mocked(useRouter);

const WEBSITES = [
  {
    id: 'site-1',
    name: 'Acme Inc',
    url: 'https://acme.example.com',
    status: 'ready',
    pages_indexed: 1,
    last_crawled_at: null,
    checksum: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    widget_id: 'widget-1',
    knowledge_status: 'ready',
    knowledge_documents: 1,
    knowledge_chunks: 5,
    last_knowledge_at: '2026-08-01T00:00:00Z',
  },
];

const CONVERSATION: ConversationSummary = {
  id: 'conv-1',
  website_id: 'site-1',
  visitor_id: 'visitor-1',
  title: 'Pricing question',
  message_count: 2,
  last_message: 'We offer three plans.',
  status: 'answered',
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-01T10:05:00Z',
};

const LIST_RESPONSE: ConversationListResponse = {
  items: [CONVERSATION],
  total: 1,
  page: 1,
  per_page: 20,
};

const DETAIL: ConversationDetail = {
  id: 'conv-1',
  website_id: 'site-1',
  visitor_id: 'visitor-1',
  title: 'Pricing question',
  status: 'answered',
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-01T10:05:00Z',
  messages: [
    {
      role: 'user',
      content: 'What are your pricing plans?',
      sources: [],
      response_time: null,
      input_tokens: 0,
      output_tokens: 0,
      created_at: '2026-08-01T10:00:00Z',
    },
    {
      role: 'assistant',
      content: 'We offer three plans.',
      sources: [{ url: 'https://example.com/page', title: 'Pricing', score: 0.9, citation: 1 }],
      response_time: 1.25,
      input_tokens: 100,
      output_tokens: 50,
      created_at: '2026-08-01T10:00:03Z',
    },
  ],
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderListPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <ConversationsPage />
    </QueryClientProvider>,
  );
}

function mockWebsites(data: unknown[] = WEBSITES) {
  mockedUseWebsites.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useWebsites>);
}

function mockConversations(
  state: Partial<ReturnType<typeof useConversations>> = {},
  data: ConversationListResponse = LIST_RESPONSE,
) {
  mockedUseConversations.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useConversations>);
}

beforeEach(() => {
  mockWebsites();
  mockConversations();
  mockedUseRouter.mockReturnValue({ replace: vi.fn() } as never);
  mockedUseDeleteConversation.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useDeleteConversation>);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('ConversationsPage', () => {
  it('shows a loading skeleton while pending', () => {
    mockConversations({ isPending: true, data: undefined });
    renderListPage();
    expect(screen.getByRole('status', { name: 'Loading conversations' })).toBeInTheDocument();
  });

  it('shows an empty state when there are no conversations', () => {
    mockConversations({ data: { items: [], total: 0, page: 1, per_page: 20 } });
    renderListPage();
    expect(screen.getByText('No conversations yet')).toBeInTheDocument();
    expect(
      screen.getByText('Chats from your widget and dashboard will appear here.'),
    ).toBeInTheDocument();
  });

  it('shows an empty state with a clear action when filters match nothing', () => {
    vi.useFakeTimers();
    mockConversations({ data: { items: [], total: 0, page: 1, per_page: 20 } });
    renderListPage();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search conversations' }), {
      target: { value: 'nothing' },
    });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.getByText('No matching conversations')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockConversations({
      isError: true,
      error: new Error('Failed to load conversations.'),
      refetch,
    });
    renderListPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load conversations.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('renders conversation rows with visitor, website and message count', () => {
    renderListPage();
    const link = screen.getByRole('link', { name: /visitor-1/ });
    expect(link).toHaveAttribute('href', '/conversations/conv-1');
    expect(within(link).getByText('We offer three plans.')).toBeInTheDocument();
    expect(within(link).getByText('Acme Inc')).toBeInTheDocument();
    expect(within(link).getByText('2 messages')).toBeInTheDocument();
    expect(within(link).getByText('Answered')).toBeInTheDocument();
  });

  it('shows a friendly label for anonymous visitors', () => {
    const anonymous = { ...CONVERSATION, id: 'conv-2', visitor_id: 'anon' };
    mockConversations({ data: { ...LIST_RESPONSE, items: [anonymous] } });
    renderListPage();
    expect(screen.getByRole('link', { name: /Anonymous/ })).toBeInTheDocument();
  });

  it('filters by website', () => {
    renderListPage();
    fireEvent.change(screen.getByLabelText('Filter by website'), {
      target: { value: 'site-1' },
    });
    const lastCall =
      mockedUseConversations.mock.calls[mockedUseConversations.mock.calls.length - 1][0];
    expect(lastCall.websiteId).toBe('site-1');
    expect(lastCall.page).toBe(1);
  });

  it('searches with a debounce and resets to the first page', () => {
    vi.useFakeTimers();
    renderListPage();
    const input = screen.getByRole('searchbox', { name: 'Search conversations' });
    fireEvent.change(input, { target: { value: 'refund' } });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    const lastCall =
      mockedUseConversations.mock.calls[mockedUseConversations.mock.calls.length - 1][0];
    expect(lastCall.search).toBe('refund');
    expect(lastCall.page).toBe(1);
  });

  it('paginates with Previous and Next controls', () => {
    mockConversations({ data: { ...LIST_RESPONSE, total: 40 } });
    renderListPage();
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    const lastCall =
      mockedUseConversations.mock.calls[mockedUseConversations.mock.calls.length - 1][0];
    expect(lastCall.page).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
    const previousCall =
      mockedUseConversations.mock.calls[mockedUseConversations.mock.calls.length - 1][0];
    expect(previousCall.page).toBe(1);
  });
});

describe('ConversationDetailPage', () => {
  function renderDetailPage() {
    return render(
      <QueryClientProvider client={makeQueryClient()}>
        <ConversationDetailPage sessionId="conv-1" />
      </QueryClientProvider>,
    );
  }

  it('shows a loading skeleton while pending', () => {
    mockedUseConversation.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    renderDetailPage();
    expect(screen.getByRole('status', { name: 'Loading conversation' })).toBeInTheDocument();
  });

  it('renders the full message history with sources and usage', () => {
    mockedUseConversation.mockReturnValue({
      data: DETAIL,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    renderDetailPage();
    expect(screen.getByRole('heading', { name: 'Pricing question' })).toBeInTheDocument();
    expect(screen.getByText('What are your pricing plans?')).toBeInTheDocument();
    expect(screen.getByText('We offer three plans.')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Pricing' })).toHaveAttribute(
      'href',
      'https://example.com/page',
    );
    expect(screen.getByText(/100 in \/ 50 out tokens/)).toBeInTheDocument();
    expect(screen.getByText(/1\.3s/)).toBeInTheDocument();
  });

  it('shows a not-found message when the conversation is missing', () => {
    mockedUseConversation.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new ApiError(404, 'SESSION_NOT_FOUND', 'Conversation not found.'),
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    renderDetailPage();
    expect(screen.getByText('Conversation not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Back to conversations/ })).toHaveAttribute(
      'href',
      '/conversations',
    );
  });

  it('deletes the conversation after confirmation and navigates back', async () => {
    const replace = vi.fn();
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseRouter.mockReturnValue({ replace } as never);
    mockedUseDeleteConversation.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteConversation
    >);
    mockedUseConversation.mockReturnValue({
      data: DETAIL,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderDetailPage();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(window.confirm).toHaveBeenCalledWith('Delete this conversation and its entire history?');
    expect(await mutateAsync).toHaveBeenCalledWith('conv-1');
    expect(toast.success).toHaveBeenCalledWith('Conversation deleted');
    expect(replace).toHaveBeenCalledWith('/conversations');
  });

  it('does not delete when confirmation is declined', () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteConversation.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteConversation
    >);
    mockedUseConversation.mockReturnValue({
      data: DETAIL,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderDetailPage();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it('renders distinct messages even when timestamps collide', () => {
    const duplicateTime: ConversationDetail = {
      ...DETAIL,
      messages: [
        {
          role: 'user',
          content: 'Hello',
          sources: [],
          response_time: null,
          input_tokens: 0,
          output_tokens: 0,
          created_at: '2026-08-01T10:00:00Z',
        },
        {
          role: 'assistant',
          content: 'Hi there',
          sources: [],
          response_time: 0.5,
          input_tokens: 10,
          output_tokens: 5,
          created_at: '2026-08-01T10:00:00Z',
        },
      ],
    };
    mockedUseConversation.mockReturnValue({
      data: duplicateTime,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConversation>);
    renderDetailPage();
    expect(screen.getByText('Hello')).toBeInTheDocument();
    expect(screen.getByText('Hi there')).toBeInTheDocument();
  });
});

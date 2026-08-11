import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useApiKeys, useRevokeApiKey } from './hooks';
import { ApiKeysPage } from './api-keys-page';
import type { ApiKey } from './types';

vi.mock('./hooks', () => ({
  useApiKeys: vi.fn(),
  useRevokeApiKey: vi.fn(),
  useCreateApiKey: vi.fn(),
}));

vi.mock('./create-api-key-dialog', () => ({
  CreateApiKeyDialog: (props: { open: boolean }) => (
    <div data-testid="create-api-key-dialog" data-open={String(props.open)} />
  ),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedUseApiKeys = vi.mocked(useApiKeys);
const mockedUseRevokeApiKey = vi.mocked(useRevokeApiKey);

const KEY: ApiKey = {
  id: 'key-1',
  tenant_id: 'tenant-1',
  name: 'Production',
  key_prefix: 'wc_',
  status: 'active',
  last_used_at: null,
  created_at: '2026-08-01T00:00:00Z',
};

function mockApiKeys(state: Partial<ReturnType<typeof useApiKeys>> = {}) {
  mockedUseApiKeys.mockReturnValue({
    data: [KEY],
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useApiKeys>);
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeysPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApiKeys();
  mockedUseRevokeApiKey.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useRevokeApiKey>);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ApiKeysPage', () => {
  it('shows a loading state while pending', () => {
    mockApiKeys({ isPending: true, data: undefined });
    renderPage();
    expect(screen.getByRole('status', { name: 'Loading API keys' })).toBeInTheDocument();
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockApiKeys({ isError: true, error: new Error('Failed to load API keys.'), refetch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load API keys.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('shows an empty state when there are no API keys', () => {
    mockApiKeys({ data: [] });
    renderPage();
    expect(screen.getByText('No API keys yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create your first API key' })).toBeInTheDocument();
  });

  it('renders the keys with a masked secret and created date', () => {
    renderPage();
    expect(screen.getByText('Production')).toBeInTheDocument();
    // The raw secret is never rendered - only the prefix plus masking dots.
    expect(screen.getByText(/^wc_•+$/)).toBeInTheDocument();
    expect(screen.getByText('Created 8/1/2026')).toBeInTheDocument();
  });

  it('opens the dialog when clicking Create API key', () => {
    renderPage();
    expect(screen.getByTestId('create-api-key-dialog')).toHaveAttribute('data-open', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Create API key' }));
    expect(screen.getByTestId('create-api-key-dialog')).toHaveAttribute('data-open', 'true');
  });

  it('revokes a key after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseRevokeApiKey.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useRevokeApiKey
    >);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Revoke' }));
    });

    expect(window.confirm).toHaveBeenCalledWith(
      'Revoke "Production"? This immediately disables the key.',
    );
    expect(mutateAsync).toHaveBeenCalledWith('key-1');
  });

  it('does not revoke when confirmation is declined', () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseRevokeApiKey.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useRevokeApiKey
    >);
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }));

    expect(mutateAsync).not.toHaveBeenCalled();
  });
});

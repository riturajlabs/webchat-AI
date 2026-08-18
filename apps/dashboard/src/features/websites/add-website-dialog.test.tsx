import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AddWebsiteDialog } from './add-website-dialog';
import { useCreateWebsite, useUpdateWebsite } from './hooks';
import type { CreateWebsiteResponse, Website } from './types';

vi.mock('./hooks', () => ({
  useCreateWebsite: vi.fn(),
  useUpdateWebsite: vi.fn(),
}));

const mockedUseCreateWebsite = vi.mocked(useCreateWebsite);
const mockedUseUpdateWebsite = vi.mocked(useUpdateWebsite);

const SITE: Website = {
  id: 'site-1',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'pending',
  pages_indexed: 0,
  last_crawled_at: null,
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  widget_id: 'widget-1',
  knowledge_status: 'none',
  knowledge_documents: 0,
  knowledge_chunks: 0,
  last_knowledge_at: null,
};

const CREATE_RESPONSE: CreateWebsiteResponse = {
  website: { ...SITE, url: 'https://acme.example.com/' },
  widget: {
    widget_id: 'widget-1',
    website_id: 'site-1',
    theme: 'light',
    position: 'bottom-right',
    primary_color: '#2563eb',
    accent_color: '#4f46e5',
    font_size: 'md',
    logo_url: null,
    avatar_url: null,
    welcome_message: 'Hi! How can I help you?',
    placeholder: 'Type your question...',
    suggested_questions: [],
    branding: true,
    dark_mode: false,
    auto_open: false,
    enabled: true,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  },
  embed_script: '<script src="http://localhost:8080/w.js" data-widget-id="widget-1"></script>',
};

beforeEach(() => {
  mockedUseCreateWebsite.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(CREATE_RESPONSE),
    isPending: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useCreateWebsite>);
  mockedUseUpdateWebsite.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(SITE),
    isPending: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useUpdateWebsite>);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AddWebsiteDialog', () => {
  it('renders the form in create mode', () => {
    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Add website' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Website URL')).toBeInTheDocument();
  });

  it('does not render when closed', () => {
    const { container } = render(<AddWebsiteDialog open={false} onOpenChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('creates a website and shows the embed script', async () => {
    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme Inc' } });
    fireEvent.change(screen.getByLabelText('Website URL'), {
      target: { value: 'https://acme.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));

    await waitFor(() => {
      expect(screen.getByText('Website added')).toBeInTheDocument();
    });
    expect(screen.queryByText('secret-abc-123')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Embed script')).toHaveValue(CREATE_RESPONSE.embed_script);
  });

  it('copies the embed script when requested', async () => {
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    vi.stubGlobal('navigator', { ...navigator, clipboard });

    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme Inc' } });
    fireEvent.change(screen.getByLabelText('Website URL'), {
      target: { value: 'https://acme.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));

    await waitFor(() => {
      expect(screen.getByText('Website added')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Copy embed code' }));

    await waitFor(() => {
      expect(clipboard.writeText).toHaveBeenCalledWith(CREATE_RESPONSE.embed_script);
    });
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('surfaces a create error', async () => {
    mockedUseCreateWebsite.mockReturnValue({
      mutateAsync: vi.fn().mockRejectedValue(new Error('A website with this URL already exists.')),
      isPending: false,
      isError: true,
      error: new Error('A website with this URL already exists.'),
    } as unknown as ReturnType<typeof useCreateWebsite>);

    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme Inc' } });
    fireEvent.change(screen.getByLabelText('Website URL'), {
      target: { value: 'https://acme.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'A website with this URL already exists.',
      );
    });
  });

  it('prefills and submits an edit', async () => {
    const onOpenChange = vi.fn();
    const mutateAsync = vi.fn().mockResolvedValue(SITE);
    mockedUseUpdateWebsite.mockReturnValue({
      mutateAsync,
      isPending: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useUpdateWebsite>);

    render(<AddWebsiteDialog open onOpenChange={onOpenChange} website={SITE} />);

    expect(screen.getByRole('heading', { name: 'Edit website' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Acme Inc');

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        websiteId: 'site-1',
        name: 'Acme Inc',
        url: 'https://acme.example.com',
      });
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  // --- Accessibility tests ---

  it('closes the dialog on Escape key', () => {
    const onOpenChange = vi.fn();
    render(<AddWebsiteDialog open onOpenChange={onOpenChange} />);

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('has aria-modal="true" on the dialog', () => {
    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('sets inert on background overlay', () => {
    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);
    const overlay = document.querySelector('[data-dialog-overlay]');
    expect(overlay).toHaveAttribute('inert');
  });

  it('traps Tab within the dialog', () => {
    render(<AddWebsiteDialog open onOpenChange={vi.fn()} />);

    // Focus the last element in the dialog (Add website submit button).
    const submitButton = screen.getByRole('button', { name: 'Add website' });
    submitButton.focus();

    // Tab should wrap to the first focusable element (Close dialog button).
    act(() => {
      fireEvent.keyDown(document, { key: 'Tab' });
    });

    const closeButton = screen.getByRole('button', { name: 'Close dialog' });
    expect(document.activeElement).toBe(closeButton);
  });
});

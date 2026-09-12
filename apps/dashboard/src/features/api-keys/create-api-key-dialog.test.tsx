import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useCreateApiKey } from './hooks';
import { CreateApiKeyDialog } from './create-api-key-dialog';

vi.mock('./hooks', () => ({
  useCreateApiKey: vi.fn(),
  useApiKeys: vi.fn(),
  useRevokeApiKey: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedUseCreateApiKey = vi.mocked(useCreateApiKey);

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <CreateApiKeyDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}

function renderHarness() {
  return render(<DialogHarness />);
}

function openDialog() {
  const trigger = screen.getByRole('button', { name: 'Open dialog' });
  // jsdom does not move focus on click; real browsers do, and the dialog's
  // focus-restoration relies on the trigger being the previously-focused element.
  trigger.focus();
  fireEvent.click(trigger);
  return screen.getByRole('dialog', { name: 'Create API key' });
}

describe('CreateApiKeyDialog', () => {
  beforeEach(() => {
    mockedUseCreateApiKey.mockReturnValue({
      error: null,
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue({
        id: 'key-1',
        api_key: 'wc_secret_123',
        tenant_id: 'tenant-1',
        name: 'Production',
        created_at: '2026-09-01T00:00:00Z',
      }),
    } as unknown as ReturnType<typeof useCreateApiKey>);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    renderHarness();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders an accessible modal dialog when open', () => {
    renderHarness();
    const dialog = openDialog();

    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-labelledby', 'create-api-key-title');
    expect(dialog).toHaveAttribute('aria-describedby', 'create-api-key-description');
    expect(document.getElementById('create-api-key-description')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
  });

  it('moves focus to the name field when opened', async () => {
    renderHarness();
    openDialog();

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());
  });

  it('traps Tab so focus wraps from last to first inside the dialog', async () => {
    renderHarness();
    const dialog = openDialog();
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());

    const createBtn = screen.getByRole('button', { name: 'Create API key' });
    const closeBtn = screen.getByRole('button', { name: 'Close dialog' });
    createBtn.focus();

    fireEvent.keyDown(document, { key: 'Tab' });

    expect(document.activeElement).toBe(closeBtn);
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('traps Shift+Tab so focus wraps from first to last inside the dialog', async () => {
    renderHarness();
    const dialog = openDialog();
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());

    const createBtn = screen.getByRole('button', { name: 'Create API key' });
    const closeBtn = screen.getByRole('button', { name: 'Close dialog' });
    closeBtn.focus();

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });

    expect(document.activeElement).toBe(createBtn);
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('cannot tab to background content while open', async () => {
    renderHarness();
    const dialog = openDialog();
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());

    // Repeated Tab presses must wrap inside the dialog, never reach the trigger.
    const createBtn = screen.getByRole('button', { name: 'Create API key' });
    createBtn.focus();
    for (let index = 0; index < 6; index++) {
      fireEvent.keyDown(document, { key: 'Tab' });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    expect(screen.getByRole('button', { name: 'Open dialog' })).not.toHaveFocus();
  });

  it('closes on Escape and restores focus to the trigger', async () => {
    renderHarness();
    openDialog();
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open dialog' })).toHaveFocus();
  });

  it('closes when the backdrop overlay is clicked (overlay stays interactive)', async () => {
    renderHarness();
    openDialog();

    const overlay = document.querySelector('[data-dialog-overlay]');
    expect(overlay).not.toHaveAttribute('inert');

    fireEvent.click(overlay as Element);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('submits the form and calls mutateAsync with the trimmed name', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      id: 'key-1',
      api_key: 'wc_secret_123',
      tenant_id: 'tenant-1',
      name: 'Production',
      created_at: '2026-09-01T00:00:00Z',
    });
    mockedUseCreateApiKey.mockReturnValue({
      error: null,
      isPending: false,
      mutateAsync,
    } as unknown as ReturnType<typeof useCreateApiKey>);

    renderHarness();
    openDialog();

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '  Production  ' } });
    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement);

    expect(mutateAsync).toHaveBeenCalledWith({ name: 'Production' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument());
  });
});

import { render, screen } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from './toaster';

describe('Toaster', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a success toast', async () => {
    render(<Toaster />);
    toast.success('Copied to clipboard');

    expect(await screen.findByText('Copied to clipboard')).toBeInTheDocument();
  });

  it('renders an error toast', async () => {
    render(<Toaster />);
    toast.error('Failed to delete website.');

    expect(await screen.findByText('Failed to delete website.')).toBeInTheDocument();
  });

  it('renders multiple toasts', async () => {
    render(<Toaster />);
    toast.success('Website added');
    toast.success('Crawl started');

    expect(await screen.findByText('Website added')).toBeInTheDocument();
    expect(screen.getByText('Crawl started')).toBeInTheDocument();
  });
});

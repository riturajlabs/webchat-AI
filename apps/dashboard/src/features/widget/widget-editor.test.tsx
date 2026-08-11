import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WidgetEditor } from './components/widget-editor';
import { useUpdateWidgetConfig } from './hooks';
import type { WidgetConfig, WidgetResponse } from './types';

vi.mock('./hooks', () => ({
  useUpdateWidgetConfig: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedUseUpdateWidgetConfig = vi.mocked(useUpdateWidgetConfig);

const CONFIG: WidgetConfig = {
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
  suggested_questions: ['What is your pricing?'],
  branding: true,
  dark_mode: false,
  auto_open: false,
  enabled: true,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

const RESPONSE: WidgetResponse = {
  widget: { ...CONFIG },
  embed_script: '<script>window.WebChatAI...</script>',
};

function setup({
  mutation = vi.fn().mockResolvedValue(RESPONSE),
}: { mutation?: ReturnType<typeof vi.fn> } = {}) {
  mockedUseUpdateWidgetConfig.mockReturnValue({
    mutateAsync: mutation,
    isPending: false,
  } as never);
  render(<WidgetEditor config={CONFIG} embedScript={RESPONSE.embed_script} />);
  return { mutation };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('WidgetEditor', () => {
  it('renders the configuration fields', () => {
    setup();

    expect(screen.getByLabelText('Theme')).toBeInTheDocument();
    expect(screen.getByLabelText('Position')).toBeInTheDocument();
    expect(screen.getByLabelText('Primary color hex value')).toBeInTheDocument();
    expect(screen.getByLabelText('Accent color hex value')).toBeInTheDocument();
    expect(screen.getByLabelText('Font size')).toBeInTheDocument();
    expect(screen.getByLabelText('Logo URL')).toBeInTheDocument();
    expect(screen.getByLabelText('Avatar URL')).toBeInTheDocument();
    expect(screen.getByLabelText('Welcome message')).toHaveValue(CONFIG.welcome_message);
    expect(screen.getByLabelText('Input placeholder')).toHaveValue(CONFIG.placeholder);
    expect(screen.getByLabelText('Show branding')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByLabelText('Auto open')).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByLabelText('Enabled')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByLabelText('Suggested question 1')).toHaveValue('What is your pricing?');
    expect(screen.getByText('Powered by WebChat AI')).toBeInTheDocument();
  });

  it('updates the preview instantly as the welcome message changes', () => {
    setup();

    expect(screen.queryByText('Hello there!')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Welcome message'), {
      target: { value: 'Hello there!' },
    });
    expect(screen.getByText('Hello there!')).toBeInTheDocument();
  });

  it('updates the preview instantly when the primary color changes', () => {
    setup();

    const send = screen.getByLabelText('Send');
    expect(send.getAttribute('style')).toContain('rgb(37, 99, 235)');

    fireEvent.change(screen.getByLabelText('Primary color color swatch'), {
      target: { value: '#ff0000' },
    });

    expect(send.getAttribute('style')).toContain('rgb(255, 0, 0)');
  });

  it('saves only the changed fields when clicking save', async () => {
    const { mutation } = setup();

    const save = screen.getByRole('button', { name: 'Save changes' });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Welcome message'), { target: { value: 'Hi there!' } });
    expect(save).toBeEnabled();

    fireEvent.click(save);

    expect(mutation).toHaveBeenCalledTimes(1);
    expect(mutation).toHaveBeenCalledWith({
      websiteId: 'site-1',
      changes: { welcome_message: 'Hi there!' },
    });
  });

  it('shows an error toast when the save fails', async () => {
    const { toast } = await import('sonner');
    const failure = new Error('Request failed with status 422');
    setup({ mutation: vi.fn().mockRejectedValue(failure) });

    fireEvent.change(screen.getByLabelText('Welcome message'), { target: { value: 'Hi there!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await vi.waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Request failed with status 422');
    });
  });
});

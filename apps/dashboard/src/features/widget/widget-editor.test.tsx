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
  theme_preset: '',
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
  bot_name: 'WebChat AI',
  bot_status_text: 'Online',
  header_color: null,
  secondary_color: null,
  background_color: null,
  text_color: null,
  font_family: null,
  width: '420px',
  height: '650px',
  border_radius: '20px',
  launcher_size: '58px',
  allowed_domains: [],
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

/** Opens the collapsed "Advanced customization" panel (Appearance section). */
function expandAdvanced() {
  fireEvent.click(screen.getByRole('button', { name: 'Advanced customization' }));
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('WidgetEditor', () => {
  it('renders the configuration fields', () => {
    setup();
    expandAdvanced();

    expect(screen.getByLabelText('Theme')).toBeInTheDocument();
    expect(screen.getByRole('radiogroup', { name: 'Theme preset' })).toBeInTheDocument();
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
    expect(screen.getAllByText('Allowed domains').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/No allowed domains — the widget is blocked from embedding/),
    ).toBeInTheDocument();
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
    expandAdvanced();

    const send = screen.getByLabelText('Send');
    expect(send.getAttribute('style')).toContain('#2563eb');

    fireEvent.change(screen.getByLabelText('Primary color color swatch'), {
      target: { value: '#ff0000' },
    });

    expect(send.getAttribute('style')).toContain('#ff0000');
  });

  it('renders the branding fields and reflects bot name changes in the preview', () => {
    setup();

    expect(screen.getByLabelText('Bot name')).toHaveValue(CONFIG.bot_name);
    expect(screen.getByLabelText('Status text')).toHaveValue(CONFIG.bot_status_text);
    expect(screen.getByLabelText('Width')).toHaveValue(CONFIG.width);
    expect(screen.getByLabelText('Height')).toHaveValue(CONFIG.height);
    expect(screen.getByLabelText('Corner radius')).toHaveValue(CONFIG.border_radius);
    expect(screen.getByLabelText('Launcher size')).toHaveValue(CONFIG.launcher_size);

    fireEvent.change(screen.getByLabelText('Bot name'), { target: { value: 'Acme Support' } });
    expect(screen.getByText('Acme Support')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Status text'), { target: { value: 'Away' } });
    expect(screen.getByText('Away')).toBeInTheDocument();
  });

  it('resets an optional branding color back to the theme default', () => {
    setup();

    const reset = screen.getAllByRole('button', { name: 'Reset to default' })[0];
    expect(reset).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Header color color swatch'), {
      target: { value: '#123456' },
    });
    expect(reset).not.toBeDisabled();

    fireEvent.click(reset);
    expect(reset).toBeDisabled();
  });

  it('hides the advanced customization panel until expanded', () => {
    setup();

    const advanced = screen.getByRole('button', { name: 'Advanced customization' });
    expect(advanced).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Position')).not.toBeInTheDocument();

    fireEvent.click(advanced);
    expect(advanced).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Position')).toBeInTheDocument();
  });

  it('applies a selected theme preset to the preview and saves it', async () => {
    const { mutation } = setup();

    const ocean = screen.getByRole('radio', { name: 'Select Ocean Blue preset' });
    expect(ocean).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'Select Classic preset' })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    fireEvent.click(ocean);
    expect(ocean).toHaveAttribute('aria-checked', 'true');

    const header = screen.getByLabelText('Close preview').closest('div');
    expect(header?.getAttribute('style')).toContain('rgb(12, 74, 110)');

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(mutation).toHaveBeenCalledWith({
      websiteId: 'site-1',
      changes: { theme_preset: 'ocean-blue' },
    });
  });

  it('switches back to the Classic preset when selected', () => {
    const withPreset: WidgetConfig = { ...CONFIG, theme_preset: 'emerald-support' };
    mockedUseUpdateWidgetConfig.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as never);
    render(<WidgetEditor config={withPreset} embedScript={RESPONSE.embed_script} />);

    const emerald = screen.getByRole('radio', { name: 'Select Emerald Support preset' });
    expect(emerald).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(screen.getByRole('radio', { name: 'Select Classic preset' }));
    expect(emerald).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'Select Classic preset' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  it('shows a custom-color override hint when a preset is active', () => {
    setup();

    expect(screen.queryByText(/override this preset/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Select Purple AI preset' }));
    expect(screen.getByText(/override this preset/)).toBeInTheDocument();
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

  it('saves added allowed domains as a single normalized change', async () => {
    const { mutation } = setup();

    const save = screen.getByRole('button', { name: 'Save changes' });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Allowed domains'), {
      target: { value: 'Acme.Example.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(screen.getByText('acme.example')).toBeInTheDocument();
    expect(save).toBeEnabled();

    fireEvent.click(save);

    expect(mutation).toHaveBeenCalledTimes(1);
    expect(mutation).toHaveBeenCalledWith({
      websiteId: 'site-1',
      changes: { allowed_domains: ['acme.example'] },
    });
  });

  it('saves removal of an allowed domain', async () => {
    const mutation = vi.fn().mockResolvedValue(RESPONSE);
    mockedUseUpdateWidgetConfig.mockReturnValue({
      mutateAsync: mutation,
      isPending: false,
    } as never);
    const withDomains = { ...CONFIG, allowed_domains: ['example.com', 'store.example.com'] };

    render(<WidgetEditor config={withDomains} embedScript={RESPONSE.embed_script} />);

    expect(screen.getByText('example.com')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove example.com' }));

    expect(screen.queryByText('example.com')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(mutation).toHaveBeenCalledWith({
      websiteId: 'site-1',
      changes: { allowed_domains: ['store.example.com'] },
    });
  });
});

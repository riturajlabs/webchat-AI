import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useWebsites } from '@/features/websites/hooks';

import { WidgetTestPage } from './widget-test-page';
import { useWidgetConfig, useWidgetPublicStatus } from './hooks';
import type { WidgetConfig } from './types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useWidgetConfig: vi.fn(),
  useWidgetPublicStatus: vi.fn(),
}));

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedUseWidgetConfig = vi.mocked(useWidgetConfig);
const mockedUseWidgetPublicStatus = vi.mocked(useWidgetPublicStatus);

const WIDGET: WidgetConfig = {
  widget_id: 'widget-test-1',
  website_id: 'site-1',
  theme: 'light',
  theme_preset: '',
  position: 'bottom-right',
  primary_color: '#2563eb',
  accent_color: '#4f46e5',
  font_size: 'md',
  logo_url: null,
  avatar_url: null,
  welcome_message: 'Hi!',
  placeholder: 'Ask...',
  suggested_questions: [],
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
  allowed_domains: ['example.com'],
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

function setup(status: {
  statusCode: number;
  enabled?: boolean;
  allowedDomains?: string[];
  errorCode?: string;
  message?: string;
}) {
  mockedUseWebsites.mockReturnValue({
    data: [{ id: 'site-1', name: 'Acme', url: 'https://example.com' }],
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  mockedUseWidgetConfig.mockReturnValue({
    data: {
      widget: WIDGET,
      embed_script:
        '<script src="http://localhost:8080/webchat-widget.iife.min.js" ' +
        'data-widget-id="widget-test-1" defer></script>',
    },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as never);
  mockedUseWidgetPublicStatus.mockReturnValue({
    data: status,
    isPending: false,
  } as never);
  render(<WidgetTestPage />);
}

describe('WidgetTestPage', () => {
  it('shows the widget id, script src, API URL and browser origin', () => {
    setup({ statusCode: 200, enabled: true, allowedDomains: ['example.com'] });

    expect(screen.getByText('widget-test-1')).toBeInTheDocument();
    expect(
      screen.getByText('http://localhost:8080/webchat-widget.iife.min.js'),
    ).toBeInTheDocument();
    expect(screen.getByText('http://localhost:8000/api/widget/v1')).toBeInTheDocument();
    expect(screen.getByText('http://localhost:3000')).toBeInTheDocument();
    expect(screen.getByTitle('Widget live preview')).toBeInTheDocument();
  });

  it('reports an allowed origin and lists the widget domains', () => {
    setup({ statusCode: 200, enabled: true, allowedDomains: ['example.com', '*.store.example'] });

    expect(screen.getByText('200 OK — this origin is permitted')).toBeInTheDocument();
    expect(screen.getByText('example.com')).toBeInTheDocument();
    expect(screen.getByText('*.store.example')).toBeInTheDocument();
  });

  it('surfaces the origin-guard code and message on a 403', () => {
    setup({
      statusCode: 403,
      errorCode: 'WIDGET_ORIGIN_NOT_ALLOWED',
      message: 'Domain evil.example is not allowed for this widget.',
    });

    expect(screen.getByText(/403 Forbidden/)).toBeInTheDocument();
    expect(screen.getByText(/WIDGET_ORIGIN_NOT_ALLOWED/)).toBeInTheDocument();
    expect(screen.getByText(/evil.example is not allowed/)).toBeInTheDocument();
  });

  it('explains the fix for an unconfigured allowlist', () => {
    setup({
      statusCode: 403,
      errorCode: 'WIDGET_DOMAIN_NOT_CONFIGURED',
      message: 'No allowed domains are configured for this widget.',
    });

    expect(screen.getByText(/WIDGET_DOMAIN_NOT_CONFIGURED/)).toBeInTheDocument();
    expect(screen.getByText(/has no allowed domains yet/)).toBeInTheDocument();
  });
});

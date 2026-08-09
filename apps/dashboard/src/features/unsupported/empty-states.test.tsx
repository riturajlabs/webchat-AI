import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AnalyticsPage } from '@/features/analytics/analytics-page';
import { ApiKeysPage } from '@/features/api-keys/api-keys-page';
import { ConversationsPage } from '@/features/conversations/conversations-page';
import { SettingsPage } from '@/features/settings/settings-page';

/**
 * Phase 7: Conversations, Analytics, API Keys and Settings have no backend
 * APIs yet. They must render production-grade empty states with a proper page
 * layout — never mock data.
 */
describe('unsupported feature pages', () => {
  it('conversations renders a layout and an empty state', () => {
    render(<ConversationsPage />);
    expect(screen.getByRole('heading', { name: 'Conversations' })).toBeInTheDocument();
    expect(screen.getByText('Conversation management is not available yet')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Conversation analytics will appear once the conversation management API is available.',
      ),
    ).toBeInTheDocument();
  });

  it('analytics renders a layout and an empty state', () => {
    render(<AnalyticsPage />);
    expect(screen.getByRole('heading', { name: 'Analytics' })).toBeInTheDocument();
    expect(screen.getByText('Analytics are not available yet')).toBeInTheDocument();
    expect(
      screen.getByText('Usage statistics will appear once the analytics API is available.'),
    ).toBeInTheDocument();
  });

  it('api keys renders a layout and an empty state', () => {
    render(<ApiKeysPage />);
    expect(screen.getByRole('heading', { name: 'API Keys' })).toBeInTheDocument();
    expect(screen.getByText('API keys are not available yet')).toBeInTheDocument();
    expect(
      screen.getByText('API key management will appear once the API key API is available.'),
    ).toBeInTheDocument();
  });

  it('settings renders a layout and an empty state', () => {
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByText('Settings editing is not available yet')).toBeInTheDocument();
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApiKeysPage } from '@/features/api-keys/api-keys-page';
import { SettingsPage } from '@/features/settings/settings-page';

/**
 * Phase 7: API Keys and Settings have no backend APIs yet. They must render
 * production-grade empty states with a proper page layout — never mock data.
 * Analytics gained a real implementation in Phase 11.3, so it is covered by
 * `features/analytics/analytics-page.test.tsx` instead.
 */
describe('unsupported feature pages', () => {
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

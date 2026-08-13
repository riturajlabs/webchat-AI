import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { buildEmbedScript } from '../embed';
import { EmbedCode } from './embed-code';

function setup({
  widgetId = 'widget_abc123',
  embedScript = buildEmbedScript('widget_abc123'),
} = {}) {
  const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
  vi.stubGlobal('navigator', { ...navigator, clipboard });
  render(<EmbedCode widgetId={widgetId} embedScript={embedScript} />);
  return { clipboard };
}

describe('EmbedCode', () => {
  it('renders the basic script and includes the widget id', () => {
    setup({ embedScript: buildEmbedScript('widget_abc123') });

    expect(screen.getByText('Basic usage — script tag')).toBeInTheDocument();
    expect(screen.getByText(/data-widget-id="widget_abc123"/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy embed script' })).toBeInTheDocument();
  });

  it('renders the advanced init() and mount() examples with the widget id', () => {
    setup({ widgetId: 'widget_xyz789' });

    expect(screen.getByText('Advanced usage — init()')).toBeInTheDocument();
    expect(screen.getByText('Advanced usage — mount()')).toBeInTheDocument();
    expect(screen.getAllByText(/widgetId: 'widget_xyz789'/).length).toBeGreaterThan(0);
    expect(screen.getByText(/document.querySelector\('#my-chat'\)/)).toBeInTheDocument();
  });

  it('copies the embed script and shows success feedback', async () => {
    const { clipboard } = setup({ embedScript: buildEmbedScript('widget_abc123') });

    fireEvent.click(screen.getByRole('button', { name: 'Copy embed script' }));

    expect(clipboard.writeText).toHaveBeenCalledWith(buildEmbedScript('widget_abc123'));
    expect(await screen.findByRole('button', { name: 'Copied!' })).toBeInTheDocument();
  });

  it('copies the init() example with the widget id', async () => {
    const { clipboard } = setup({ widgetId: 'widget_abc123' });

    fireEvent.click(screen.getByRole('button', { name: 'Copy init() example' }));

    const written = clipboard.writeText.mock.calls[0][0] as string;
    expect(written).toContain("widgetId: 'widget_abc123'");
    expect(written).toContain("import { init } from '@webchat/widget'");
  });

  it('copies the mount() example', async () => {
    const { clipboard } = setup();

    fireEvent.click(screen.getByRole('button', { name: 'Copy mount() example' }));

    const written = clipboard.writeText.mock.calls[0][0] as string;
    expect(written).toContain("import { mount } from '@webchat/widget'");
    expect(written).toContain("host: document.querySelector('#my-chat')");
  });

  it('never surfaces localhost in the generated examples', () => {
    setup();

    const bodyText = document.body.textContent ?? '';
    expect(bodyText.toLowerCase()).not.toContain('localhost');
    expect(bodyText.toLowerCase()).not.toContain('127.0.0.1');
  });
});

import { describe, expect, it } from 'vitest';
import axe from 'axe-core';
import { createChatWindow } from './window';
import { createComposer } from './composer';
import { createLauncher } from './launcher';
import { defaultConfig } from '../config/types';
import { createBubble, createMessageList } from './bubbles';

/**
 * M5.3: axe-core accessibility audit over the widget UI.
 *
 * axe cannot pierce the widget's closed shadow root, so each component is
 * rendered as real DOM in the test body and audited directly.
 */

type Violation = { id: string; impact?: string; help: string; nodes: unknown[] };

async function runAxe(container: HTMLElement): Promise<Violation[]> {
  const results = await axe.run(container, {
    rules: {
      'color-contrast': { enabled: false }, // theme-dependent, verified visually
    },
  });
  return (results.violations as unknown as Violation[]).filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
}

describe('widget accessibility (axe-core)', () => {
  it('audits the open chat window with content and no serious/critical violations', async () => {
    const config = defaultConfig('widget_1');
    const messagesElement = createMessageList();
    const windowApi = createChatWindow({
      config,
      messagesElement,
      onSend: () => {},
      onClose: () => {},
      onSuggested: () => {},
      onRetry: () => {},
      onDismiss: () => {},
      isDisabled: () => false,
    });

    // Populate messages, a retryable banner, and suggested questions.
    messagesElement.appendChild(createBubble({ id: 'u1', role: 'user', content: 'Hi' }));
    messagesElement.appendChild(
      createBubble({ id: 'a1', role: 'assistant', content: 'Hello! What can I help with?' }),
    );
    messagesElement.appendChild(
      createBubble({ id: 'a2', role: 'assistant', content: '', error: true }),
    );
    windowApi.syncSuggested(['What is pricing?', 'Docs']);
    windowApi.setBanner("Can't reach the assistant", true);

    document.body.appendChild(windowApi.element);
    try {
      const violations = await runAxe(windowApi.element);
      expect(violations).toEqual([]);
    } finally {
      windowApi.element.remove();
    }
  });

  it('audits the launcher toggle', async () => {
    const launcher = createLauncher({
      position: 'bottom-right',
      onToggle: () => {},
      isOpen: () => false,
    });
    document.body.appendChild(launcher);
    try {
      const violations = await runAxe(launcher);
      expect(violations).toEqual([]);
    } finally {
      launcher.remove();
    }
  });

  it('audits the composer in isolation', async () => {
    const composer = createComposer({
      placeholder: 'Type your message…',
      onSend: () => {},
      isDisabled: () => false,
    });
    document.body.appendChild(composer.element);
    try {
      const violations = await runAxe(composer.element);
      expect(violations).toEqual([]);
    } finally {
      composer.element.remove();
    }
  });
});

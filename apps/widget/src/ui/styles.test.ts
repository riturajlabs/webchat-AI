import { describe, expect, it } from 'vitest';
import { WIDGET_STYLES } from './styles';

/**
 * Regression coverage for the horizontal-overflow containment contract:
 * wide markdown tables and long tokens must never widen the widget; any
 * required horizontal scrolling happens inside the assistant bubble.
 */
describe('WIDGET_STYLES overflow containment', () => {
  it('caps the bubble width and neutralizes flex min-size blowout', () => {
    expect(WIDGET_STYLES).toMatch(/\.wc-bubble\s*\{[^}]*max-width:\s*82%/);
    expect(WIDGET_STYLES).toMatch(/\.wc-bubble\s*\{[^}]*min-width:\s*0;/);
  });

  it('prevents the conversation list from scrolling horizontally', () => {
    expect(WIDGET_STYLES).toMatch(/\.wc-messages\s*\{[^}]*overflow-x:\s*clip;/);
  });

  it('scrolls wide tables locally inside the bubble', () => {
    const wrapper = /\.wc-bubble-content\s+\.wc-table-scroll\s*\{([^}]*)\}/.exec(WIDGET_STYLES);
    expect(wrapper).toBeTruthy();
    expect(wrapper![1]).toContain('overflow-x: auto');
    expect(wrapper![1]).toContain('max-width: 100%');
    expect(wrapper![1]).toContain('overscroll-behavior-x: contain');
    expect(wrapper![1]).toContain('touch-action: pan-x pan-y');
  });

  it('keeps table columns at their natural readable width', () => {
    const table = /\.wc-bubble-content\s+\.wc-table-scroll\s+table\s*\{([^}]*)\}/.exec(
      WIDGET_STYLES,
    );
    expect(table).toBeTruthy();
    expect(table![1]).toContain('width: 100%');
    expect(table![1]).toContain('min-width: max-content');
  });

  it('keeps a comfortable bottom inset so the last message clears the composer', () => {
    const messages = /\.wc-messages\s*\{([^}]*)\}/.exec(WIDGET_STYLES);
    expect(messages).toBeTruthy();
    expect(messages![1]).toMatch(/padding:\s*14px\s+14px\s+12px;/);
  });
});

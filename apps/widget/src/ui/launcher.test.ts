import { describe, expect, it, vi } from 'vitest';
import { createLauncher, syncLauncher } from './launcher';

describe('createLauncher', () => {
  it('is a real button with aria-label and toggles on click', () => {
    let open = false;
    const onToggle = vi.fn((next: boolean) => {
      open = next;
    });
    const button = createLauncher({
      position: 'bottom-right',
      isOpen: () => open,
      onToggle,
    });
    expect(button.tagName).toBe('BUTTON');
    expect(button.getAttribute('aria-label')).toBe('Chat widget');
    expect(button.getAttribute('aria-expanded')).toBe('false');

    button.click();
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it('syncLauncher reflects open state in aria-expanded', () => {
    let open = false;
    const button = createLauncher({
      position: 'bottom-left',
      isOpen: () => open,
      onToggle: () => undefined,
    });
    syncLauncher(button, true);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(button.classList.contains('wc-is-open')).toBe(true);
  });
});

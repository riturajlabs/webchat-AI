import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ALL_THEMES, CLASSIC, ThemeItem, ThemeSelector } from './theme-selector';
import { THEME_PRESETS } from '@webchat/themes';

describe('ThemeSelector', () => {
  // 1. Initially renders exactly 6 cards.
  it('initially renders exactly 6 cards', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(6);
  });

  // 2. Initial button is "Show more (5 more)".
  it('initial button is "Show more (5 more)"', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);
    const remaining = ALL_THEMES.length - 6;
    expect(
      screen.getByRole('button', { name: `Show more (${remaining} more)` }),
    ).toBeInTheDocument();
  });

  // 3. Clicking Show more renders all 11 themes.
  it('clicking Show more renders all 11 themes', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);
    const showMore = screen.getByRole('button', { name: /Show more/i });
    fireEvent.click(showMore);
    expect(screen.getAllByRole('radio')).toHaveLength(ALL_THEMES.length);
  });

  // 4 & 5. After expansion button remains visible and says "Show less".
  it('after expansion button remains visible and says "Show less"', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);
    const showMore = screen.getByRole('button', { name: /Show more/i });
    fireEvent.click(showMore);

    const showLess = screen.getByRole('button', { name: 'Show less' });
    expect(showLess).toBeInTheDocument();
    expect(showLess).toHaveAttribute('aria-expanded', 'true');
  });

  // 6 & 7. Clicking Show less returns to 6 visible themes and button returns to "Show more (5 more)".
  it('clicking Show less returns to 6 visible themes and button returns to "Show more (5 more)"', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);
    const showMore = screen.getByRole('button', { name: /Show more/i });
    fireEvent.click(showMore);
    expect(screen.getAllByRole('radio')).toHaveLength(ALL_THEMES.length);

    const showLess = screen.getByRole('button', { name: 'Show less' });
    fireEvent.click(showLess);

    expect(screen.getAllByRole('radio')).toHaveLength(6);
    expect(screen.getByRole('button', { name: /Show more \(5 more\)/i })).toBeInTheDocument();
  });

  // 8. Active theme beyond first 6 automatically starts expanded.
  it('active theme beyond first 6 automatically starts expanded', () => {
    // 1 Classic + 5 presets = indices 0..5 are initial. Index 6 is out of range.
    const outOfRangePreset = THEME_PRESETS[5]; // 6th preset, so index 6 overall
    render(<ThemeSelector value={outOfRangePreset.id} onChange={vi.fn()} />);

    expect(screen.getAllByRole('radio')).toHaveLength(ALL_THEMES.length);
    const activeRadio = screen.getByRole('radio', {
      name: `Select ${outOfRangePreset.name} preset`,
    });
    expect(activeRadio).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('button', { name: 'Show less' })).toBeInTheDocument();
  });

  // 9. Active out-of-range theme is not hidden when attempting to collapse (Option A).
  it('active out-of-range theme is not hidden when attempting to collapse (Option A)', () => {
    const outOfRangePreset = THEME_PRESETS[5];
    render(<ThemeSelector value={outOfRangePreset.id} onChange={vi.fn()} />);

    const showLess = screen.getByRole('button', { name: 'Show less' });
    fireEvent.click(showLess);

    // Stays expanded to prevent active theme from being hidden
    expect(screen.getAllByRole('radio')).toHaveLength(ALL_THEMES.length);
    const activeRadio = screen.getByRole('radio', {
      name: `Select ${outOfRangePreset.name} preset`,
    });
    expect(activeRadio).toBeInTheDocument();
    expect(activeRadio).toHaveAttribute('aria-checked', 'true');
  });

  // 10. Radio/selection behavior continues to work.
  it('radio and selection behavior continues to work', () => {
    const onChange = vi.fn();
    render(<ThemeSelector value={CLASSIC} onChange={onChange} />);

    const firstPreset = THEME_PRESETS[0];
    const presetRadio = screen.getByRole('radio', { name: `Select ${firstPreset.name} preset` });
    fireEvent.click(presetRadio);
    expect(onChange).toHaveBeenCalledWith(firstPreset.id);

    const classicRadio = screen.getByRole('radio', { name: 'Select Classic preset' });
    fireEvent.click(classicRadio);
    expect(onChange).toHaveBeenCalledWith(CLASSIC);
  });

  it('does not render toggle button when total themes is exactly 6', () => {
    const sixThemes: ThemeItem[] = ALL_THEMES.slice(0, 6);
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} themes={sixThemes} />);
    expect(screen.getAllByRole('radio')).toHaveLength(6);
    expect(screen.queryByRole('button', { name: /Show/i })).not.toBeInTheDocument();
  });

  it('does not render toggle button when total themes is fewer than 6', () => {
    const fourThemes: ThemeItem[] = ALL_THEMES.slice(0, 4);
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} themes={fourThemes} />);
    expect(screen.getAllByRole('radio')).toHaveLength(4);
    expect(screen.queryByRole('button', { name: /Show/i })).not.toBeInTheDocument();
  });
});

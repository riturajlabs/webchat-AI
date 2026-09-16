import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ALL_THEMES, CLASSIC, ThemeItem, ThemeSelector } from './theme-selector';
import { THEME_PRESETS } from '@webchat/themes';

describe('ThemeSelector', () => {
  it('renders exactly 6 theme cards initially when total themes > 6', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);

    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(6);
  });

  it('renders Show more button with dynamic remaining count when total > 6', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);

    const remaining = ALL_THEMES.length - 6;
    expect(
      screen.getByRole('button', { name: `Show more (${remaining} more)` }),
    ).toBeInTheDocument();
  });

  it('reveals all themes and removes Show more upon clicking Show more', () => {
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} />);

    const showMore = screen.getByRole('button', { name: /Show more/i });
    fireEvent.click(showMore);

    expect(screen.getAllByRole('radio')).toHaveLength(ALL_THEMES.length);
    expect(screen.queryByRole('button', { name: /Show more/i })).not.toBeInTheDocument();
  });

  it('does not render Show more when total themes is exactly 6', () => {
    const exactlySix: ThemeItem[] = ALL_THEMES.slice(0, 6);
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} themes={exactlySix} />);

    expect(screen.getAllByRole('radio')).toHaveLength(6);
    expect(screen.queryByRole('button', { name: /Show more/i })).not.toBeInTheDocument();
  });

  it('does not render Show more when total themes is fewer than 6', () => {
    const fourThemes: ThemeItem[] = ALL_THEMES.slice(0, 4);
    render(<ThemeSelector value={CLASSIC} onChange={vi.fn()} themes={fourThemes} />);

    expect(screen.getAllByRole('radio')).toHaveLength(4);
    expect(screen.queryByRole('button', { name: /Show more/i })).not.toBeInTheDocument();
  });

  it('allows selecting Classic and triggers onChange with empty string', () => {
    const onChange = vi.fn();
    render(<ThemeSelector value="whatsapp-classic" onChange={onChange} />);

    const classicRadio = screen.getByRole('radio', { name: 'Select Classic preset' });
    fireEvent.click(classicRadio);

    expect(onChange).toHaveBeenCalledWith(CLASSIC);
  });

  it('allows selecting a preset theme and triggers onChange with preset id', () => {
    const onChange = vi.fn();
    render(<ThemeSelector value={CLASSIC} onChange={onChange} />);

    const firstPreset = THEME_PRESETS[0];
    const presetRadio = screen.getByRole('radio', { name: `Select ${firstPreset.name} preset` });
    fireEvent.click(presetRadio);

    expect(onChange).toHaveBeenCalledWith(firstPreset.id);
  });

  it('preserves selected state across expansion', () => {
    const selectedPreset = THEME_PRESETS[0];
    render(<ThemeSelector value={selectedPreset.id} onChange={vi.fn()} />);

    const showMore = screen.getByRole('button', { name: /Show more/i });
    fireEvent.click(showMore);

    const activeRadio = screen.getByRole('radio', { name: `Select ${selectedPreset.name} preset` });
    expect(activeRadio).toHaveAttribute('aria-checked', 'true');
  });
});

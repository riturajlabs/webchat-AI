import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeToggle } from './theme-toggle';

vi.mock('next-themes', () => ({
  useTheme: vi.fn(),
}));

import { useTheme } from 'next-themes';

const mockedUseTheme = vi.mocked(useTheme);

describe('ThemeToggle', () => {
  beforeEach(() => {
    mockedUseTheme.mockReturnValue({
      theme: 'system',
      setTheme: vi.fn(),
    } as never);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders a trigger button with the current theme label', () => {
    render(<ThemeToggle />);
    expect(screen.getByRole('button', { name: 'Theme: system' })).toBeInTheDocument();
  });

  it('opens the menu with all theme options', () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: 'Theme: system' }));

    expect(screen.getByRole('menu', { name: 'Theme' })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: /Light/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: /Dark/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: /System/ })).toBeInTheDocument();
  });

  it('sets the theme when an option is selected and closes the menu', () => {
    const setTheme = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'light', setTheme } as never);

    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: 'Theme: light' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Dark/ }));

    expect(setTheme).toHaveBeenCalledWith('dark');
    expect(screen.queryByRole('menu', { name: 'Theme' })).not.toBeInTheDocument();
  });

  it('marks the active theme option as checked', () => {
    mockedUseTheme.mockReturnValue({
      theme: 'dark',
      setTheme: vi.fn(),
    } as never);

    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: 'Theme: dark' }));

    expect(screen.getByRole('menuitemradio', { name: /Dark/ })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByRole('menuitemradio', { name: /Light/ })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('closes the menu when Escape is pressed', () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: 'Theme: system' }));
    expect(screen.getByRole('menu', { name: 'Theme' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('menu', { name: 'Theme' })).not.toBeInTheDocument();
  });
});

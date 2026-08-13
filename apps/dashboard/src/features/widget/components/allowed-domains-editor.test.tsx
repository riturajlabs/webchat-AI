import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MAX_ALLOWED_DOMAINS } from '../domain';
import { AllowedDomainsEditor } from './allowed-domains-editor';

function setup(domains: string[] = []) {
  const onChange = vi.fn();
  render(<AllowedDomainsEditor domains={domains} onChange={onChange} />);
  return { onChange };
}

describe('AllowedDomainsEditor', () => {
  it('renders the current domains and an empty state', () => {
    setup(['example.com', '*.store.example']);

    expect(screen.getByText('example.com')).toBeInTheDocument();
    expect(screen.getByText('*.store.example')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove example.com')).toBeInTheDocument();
    expect(screen.queryByText(/any website can embed/)).not.toBeInTheDocument();
  });

  it('shows an empty state when there are no domains', () => {
    setup();

    expect(screen.getByText(/any website can embed/)).toBeInTheDocument();
    expect(screen.getByText(`0/${MAX_ALLOWED_DOMAINS}`)).toBeInTheDocument();
  });

  it('adds a normalized domain', () => {
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText('Allowed domains'), {
      target: { value: '  Acme.Example.  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(onChange).toHaveBeenCalledWith(['acme.example']);
    expect(screen.getByLabelText('Allowed domains')).toHaveValue('');
  });

  it('adds on Enter', () => {
    const { onChange } = setup();

    const input = screen.getByLabelText('Allowed domains');
    fireEvent.change(input, { target: { value: 'store.example.com' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onChange).toHaveBeenCalledWith(['store.example.com']);
  });

  it('rejects invalid entries with a clear error', () => {
    const { onChange } = setup();

    fireEvent.change(screen.getByLabelText('Allowed domains'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(onChange).not.toHaveBeenCalled();
    expect(
      screen.getByText('Use a bare hostname like example.com (optionally *.example.com).'),
    ).toBeInTheDocument();
  });

  it('rejects duplicates', () => {
    const { onChange } = setup(['example.com']);

    fireEvent.change(screen.getByLabelText('Allowed domains'), {
      target: { value: 'EXAMPLE.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText('example.com is already in the list.')).toBeInTheDocument();
  });

  it('clears the error when the input changes', () => {
    setup();

    fireEvent.change(screen.getByLabelText('Allowed domains'), {
      target: { value: 'https://example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByRole('alert')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Allowed domains'), { target: { value: 'example' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('removes a domain', () => {
    const { onChange } = setup(['example.com', 'store.example.com']);

    fireEvent.click(screen.getByRole('button', { name: 'Remove example.com' }));

    expect(onChange).toHaveBeenCalledWith(['store.example.com']);
  });
});

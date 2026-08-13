import { describe, expect, it } from 'vitest';

import { MAX_DOMAIN_LENGTH, normalizeDomain } from './domain';

describe('normalizeDomain', () => {
  it('normalizes case, whitespace and trailing dots', () => {
    expect(normalizeDomain('  Acme.Example.  ')).toBe('acme.example');
    expect(normalizeDomain('example.com.')).toBe('example.com');
  });

  it('preserves wildcard prefixes', () => {
    expect(normalizeDomain('*.Sub.Example')).toBe('*.sub.example');
    expect(normalizeDomain('*')).toBe('*');
  });

  it('rejects empty entries', () => {
    expect(normalizeDomain('')).toBeNull();
    expect(normalizeDomain('   ')).toBeNull();
    expect(normalizeDomain('*')).toBe('*');
    expect(normalizeDomain('*.')).toBe('*');
  });

  it('rejects schemes, ports, paths and invalid characters', () => {
    expect(normalizeDomain('https://example.com')).toBeNull();
    expect(normalizeDomain('example.com/path')).toBeNull();
    expect(normalizeDomain('example.com:8080')).toBeNull();
    expect(normalizeDomain('not a hostname')).toBeNull();
    expect(normalizeDomain('example?query=1')).toBeNull();
  });

  it('rejects malformed labels', () => {
    expect(normalizeDomain('.example.com')).toBeNull();
    expect(normalizeDomain('example..com')).toBeNull();
    expect(normalizeDomain('-example.com')).toBeNull();
    expect(normalizeDomain('example-.com')).toBeNull();
  });

  it('rejects entries that exceed the DNS length limit', () => {
    expect(normalizeDomain(`${'a'.repeat(MAX_DOMAIN_LENGTH)}.com`)).toBeNull();
    expect(normalizeDomain('a'.repeat(MAX_DOMAIN_LENGTH))).not.toBeNull();
  });
});

import { describe, expect, it } from 'vitest';

import { MAX_DOMAIN_LENGTH, normalizeDomain } from './domain';

describe('normalizeDomain', () => {
  it('normalizes case, whitespace and trailing dots', () => {
    expect(normalizeDomain('  Acme.Example.  ')).toBe('acme.example');
    expect(normalizeDomain('example.com.')).toBe('example.com');
    expect(normalizeDomain('localhost.')).toBe('localhost');
  });

  it('preserves wildcard prefixes', () => {
    expect(normalizeDomain('*.Sub.Example')).toBe('*.sub.example');
    expect(normalizeDomain('*')).toBe('*');
    expect(normalizeDomain('*.')).toBe('*');
  });

  it('accepts loopback hosts as single labels', () => {
    expect(normalizeDomain('localhost')).toBe('localhost');
    expect(normalizeDomain('127.0.0.1')).toBe('127.0.0.1');
  });

  it('rejects empty entries', () => {
    expect(normalizeDomain('')).toBeNull();
    expect(normalizeDomain('   ')).toBeNull();
  });

  it('reduces full http(s) URLs to their hostname', () => {
    expect(normalizeDomain('https://example.com')).toBe('example.com');
    expect(normalizeDomain('http://localhost:3000')).toBe('localhost');
    expect(normalizeDomain('https://www.example.com/dashboard')).toBe('www.example.com');
    expect(normalizeDomain('https://example.com/path?query=1#hash')).toBe('example.com');
    expect(normalizeDomain('HTTPS://SUBDOMAIN.EXAMPLE.COM')).toBe('subdomain.example.com');
  });

  it('rejects non-http(s) URLs and malformed URLs', () => {
    expect(normalizeDomain('ftp://example.com')).toBeNull();
    expect(normalizeDomain('file:///tmp/page.html')).toBeNull();
    expect(normalizeDomain('https://')).toBeNull();
    expect(normalizeDomain('http://')).toBeNull();
  });

  it('rejects ports, paths, invalid characters and bare single-label typos', () => {
    expect(normalizeDomain('example.com/path')).toBeNull();
    expect(normalizeDomain('example.com:8080')).toBeNull();
    expect(normalizeDomain('localhost:3000')).toBeNull();
    expect(normalizeDomain('not a hostname')).toBeNull();
    expect(normalizeDomain('example?query=1')).toBeNull();
    expect(normalizeDomain('example')).toBeNull();
    expect(normalizeDomain('*.localhost')).toBeNull();
  });

  it('rejects malformed labels', () => {
    expect(normalizeDomain('.example.com')).toBeNull();
    expect(normalizeDomain('example..com')).toBeNull();
    expect(normalizeDomain('-example.com')).toBeNull();
    expect(normalizeDomain('example-.com')).toBeNull();
  });

  it('rejects entries that exceed the DNS length limit', () => {
    expect(normalizeDomain(`${'a'.repeat(MAX_DOMAIN_LENGTH)}.com`)).toBeNull();
    expect(normalizeDomain(`${'a'.repeat(MAX_DOMAIN_LENGTH - 4)}.com`)).toBe(
      `${'a'.repeat(MAX_DOMAIN_LENGTH - 4)}.com`,
    );
  });
});

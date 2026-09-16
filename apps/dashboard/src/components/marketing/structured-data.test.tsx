import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  FaqJsonLd,
  MarketingStructuredData,
  OrganizationJsonLd,
  SoftwareApplicationJsonLd,
  WebSiteJsonLd,
} from './structured-data';

describe('Structured Data Components', () => {
  it('OrganizationJsonLd renders valid organization schema with logo.png', () => {
    const { container } = render(<OrganizationJsonLd />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent || '{}');
    expect(data['@type']).toBe('Organization');
    expect(data.logo).toMatch(/\/logo\.png$/);
  });

  it('WebSiteJsonLd renders valid WebSite schema', () => {
    const { container } = render(<WebSiteJsonLd />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent || '{}');
    expect(data['@type']).toBe('WebSite');
    expect(data.name).toBeDefined();
    expect(data.url).toBeDefined();
  });

  it('SoftwareApplicationJsonLd renders valid SoftwareApplication schema', () => {
    const { container } = render(<SoftwareApplicationJsonLd />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent || '{}');
    expect(data['@type']).toBe('SoftwareApplication');
    expect(data.applicationCategory).toBe('BusinessApplication');
  });

  it('MarketingStructuredData includes Organization, WebSite, and SoftwareApplication schemas without Faq', () => {
    const { container } = render(<MarketingStructuredData />);
    const scripts = container.querySelectorAll('script[type="application/ld+json"]');
    expect(scripts).toHaveLength(3);
    const parsed = Array.from(scripts).map((s) => JSON.parse(s.textContent || '{}'));
    const types = parsed.map((p) => p['@type']);
    expect(types).toContain('Organization');
    expect(types).toContain('WebSite');
    expect(types).toContain('SoftwareApplication');
    expect(types).not.toContain('FAQPage');
  });

  it('FaqJsonLd renders valid FAQPage schema', () => {
    const { container } = render(<FaqJsonLd />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent || '{}');
    expect(data['@type']).toBe('FAQPage');
    expect(Array.isArray(data.mainEntity)).toBe(true);
    expect(data.mainEntity.length).toBeGreaterThan(0);
  });
});

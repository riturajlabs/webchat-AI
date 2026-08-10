import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './render';

const XSS_CORPUS: string[] = [
  '<script>alert(1)</script>',
  '[click](javascript:alert(1))',
  '[click](data:text/html,<script>alert(1)</script>)',
  '[click](vbscript:msgbox(1))',
  '<img src=x onerror=alert(1)>',
  '<div onclick="alert(1)">click</div>',
  '<iframe src="https://evil.example"></iframe>',
  '<object data="https://evil.example"></object>',
  '<embed src="https://evil.example">',
  '<style>body{display:none}</style>',
  '<svg onload=alert(1)>',
  '![alt](https://evil.example/x.png)',
  '<h1 onclick=alert(1)>title</h1>',
  'javascript:alert(1)',
];

describe('renderMarkdown', () => {
  it('renders bold and italic', () => {
    const html = renderMarkdown('**bold** and *italic*');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>italic</em>');
  });

  it('renders inline code', () => {
    const html = renderMarkdown('run `npm test`');
    expect(html).toContain('<code>npm test</code>');
  });

  it('renders safe links with rel noopener', () => {
    const html = renderMarkdown('[docs](https://example.com)');
    expect(html).toContain('<a href="https://example.com"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('target="_blank"');
  });

  it('renders headings, lists, blockquotes and fenced code', () => {
    const html = renderMarkdown(
      [
        '# Title',
        '## Sub',
        '- one',
        '- two',
        '1. first',
        '> quote',
        '```js',
        'const x = 1;',
        '```',
      ].join('\n'),
    );
    expect(html).toContain('<h3>');
    expect(html).toContain('<li>one</li>');
    expect(html).toContain('<blockquote>');
    expect(html).toContain('<pre><code>');
  });

  it('rejects raw script tags entirely', () => {
    const html = renderMarkdown('<script>alert(1)</script>');
    expect(html).not.toContain('<script');
    expect(html.toLowerCase()).not.toContain('alert');
  });

  it('rejects dangerous link schemes, keeping the visible text', () => {
    for (const payload of XSS_CORPUS.slice(1, 4)) {
      const html = renderMarkdown(payload);
      expect(html).not.toContain('javascript:');
      expect(html).not.toContain('data:text');
      expect(html).not.toContain('vbscript:');
      expect(html).toContain('click');
      expect(html).not.toContain('<a ');
    }
  });

  it('escapes raw HTML so it can never become live elements or handlers', () => {
    for (const payload of XSS_CORPUS.slice(4)) {
      const html = renderMarkdown(payload);
      // Raw HTML becomes escaped text: no real elements, no real attributes.
      expect(html).not.toMatch(/<[a-z][a-z0-9]*\s[^>]*(onerror|onload|onclick)\s*=/i);
      expect(html).not.toMatch(/<(iframe|object|embed|style|svg|img|h1|div|a)\b/i);
    }
  });

  it('escapes stray autolinks and emails to text', () => {
    const html = renderMarkdown('see https://example.com or mail@example.com');
    expect(html).not.toContain('<a ');
    expect(html).not.toMatch(/<(?:a|img|iframe)/);
  });

  it('strips raw HTML tags, never passing them through', () => {
    const html = renderMarkdown('hello <b>world</b> <div>block</div>');
    expect(html).not.toContain('<div>');
    expect(html).not.toContain('<b>world</b>');
  });

  it('renders empty input as empty string', () => {
    expect(renderMarkdown('')).toBe('');
  });
});

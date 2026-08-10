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

  it('renders strikethrough', () => {
    const html = renderMarkdown('~~gone~~ and `~~code~~`');
    expect(html).toContain('<del>gone</del>');
    expect(html).toContain('<code>~~code~~</code>');
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

  it('renders headings, nested lists, blockquotes and fenced code with lang+copy', () => {
    const html = renderMarkdown(
      [
        '# Title',
        '## Sub',
        '- one',
        '  - nested',
        '  - deeper',
        '- two',
        '1. first',
        '> quote',
        '```js',
        'const x = 1;',
        '```',
      ].join('\n'),
    );
    expect(html).toContain('<h3>');
    expect(html).toContain('<ul><li>one</li><ul><li>nested</li>');
    expect(html).toContain('<blockquote>');
    expect(html).toContain('<pre class="wc-code">');
    expect(html).toContain('<span class="wc-code-lang">js</span>');
    expect(html).toContain('class="wc-code-copy"');
    expect(html).toContain('>Copy</button>');
  });

  it('renders GFM tables with header/body and alignment', () => {
    const html = renderMarkdown(
      ['| Name | Qty |', '| :--- | ---: |', '| A    | 1   |', '| B    | 2   |'].join('\n'),
    );
    expect(html).toContain(
      '<table><thead><tr><th align="left">Name</th><th align="right">Qty</th>',
    );
    expect(html).toContain('<td align="left">A</td><td align="right">1</td>');
    expect(html).toContain('</tbody></table>');
  });

  it('renders a non-table pipe line as a paragraph', () => {
    const html = renderMarkdown('| not | a table |');
    expect(html).not.toContain('<table');
    expect(html).toContain('<p>');
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
      expect(html).not.toMatch(/<[a-z][a-z0-9]*\s[^>]*(onerror|onload|onclick)\s*=/i);
      expect(html).not.toMatch(/<(iframe|object|embed|style|svg|img|h1|div|a)\b/i);
    }
  });

  it('strips event-handler attributes injected inside tables and code', () => {
    const html = renderMarkdown(
      ['| <img src=x onerror=alert(1)> |', '| --- |', '| x |'].join('\n'),
    );
    // Raw HTML is escaped to inert text: no real img element, no live attribute.
    expect(html).not.toMatch(/<[a-z][^>]*onerror\s*=/i);
    expect(html).not.toMatch(/<img\b/i);
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

  it('strips event handlers from copy buttons (defense in depth)', () => {
    const html = renderMarkdown('```\n<script>alert(1)</script>\n```');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script');
    expect(html).not.toMatch(/onclick\s*=/i);
  });
});

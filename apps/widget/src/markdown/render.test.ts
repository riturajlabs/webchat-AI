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

  it('renders GFM tables with header/body and alignment inside a scroll wrapper', () => {
    const html = renderMarkdown(
      ['| Name | Qty |', '| :--- | ---: |', '| A    | 1   |', '| B    | 2   |'].join('\n'),
    );
    expect(html).toContain(
      '<div class="wc-table-scroll"><table><thead><tr><th align="left">Name</th><th align="right">Qty</th>',
    );
    expect(html).toContain('<td align="left">A</td><td align="right">1</td>');
    expect(html).toContain('</tbody></table></div>');
  });

  it('closes the table wrapper before a following paragraph', () => {
    const html = renderMarkdown(
      ['| A | B |', '| --- | --- |', '| 1 | 2 |', '', 'Text after'].join('\n'),
    );
    expect(html).toContain('</tbody></table></div><p>Text after</p>');
  });

  it('emits balanced wrapper markup when a table is cut off mid-stream', () => {
    const html = renderMarkdown(
      ['| School | Programs |', '| --- | --- |', '| B. Com – A'].join('\n'),
    );
    const wrappers = html.match(/<div class="wc-table-scroll">/g) ?? [];
    expect(wrappers).toHaveLength(1);
    expect(html).toContain('</tbody></table></div>');
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

  describe('list streaming (Phase 2)', () => {
    it('handles partial ordered item "1. "', () => {
      const html = renderMarkdown('1. ');
      expect(html).toBe('<ol><li></li></ol>');
    });

    it('handles partial ordered item continuation "1. " + "BBA"', () => {
      const html1 = renderMarkdown('1. ');
      expect(html1).toBe('<ol><li></li></ol>');
      const html2 = renderMarkdown('1. BBA');
      expect(html2).toBe('<ol><li>BBA</li></ol>');
    });

    it('handles sequential ordered list items "1. A\\n2. B\\n3. C"', () => {
      const html = renderMarkdown('1. A\n2. B\n3. C');
      expect(html).toBe('<ol><li>A</li><li>B</li><li>C</li></ol>');
    });

    it('preserves start=4 on ordered lists starting at 4 ("4. Four\\n5. Five")', () => {
      const html = renderMarkdown('4. Four\n5. Five');
      expect(html).toBe('<ol start="4"><li>Four</li><li>Five</li></ol>');
    });

    it('preserves list container across blank lines (loose lists)', () => {
      const html = renderMarkdown('1. A\n\n2. B');
      expect(html).toBe('<ol><li>A</li><li>B</li></ol>');
    });

    it('preserves list container across trailing newline deltas', () => {
      const html = renderMarkdown('1. A\n');
      expect(html).toBe('<ol><li>A</li></ol>');
    });

    it('handles partial unordered item "-"', () => {
      const html = renderMarkdown('-');
      expect(html).toBe('<ul><li></li></ul>');
    });

    it('handles partial unordered item "*"', () => {
      const html = renderMarkdown('*');
      expect(html).toBe('<ul><li></li></ul>');
    });

    it('handles partial unordered item "+"', () => {
      const html = renderMarkdown('+');
      expect(html).toBe('<ul><li></li></ul>');
    });

    it('supports nested lists', () => {
      const html = renderMarkdown('- parent\n  - child\n    - grandchild');
      expect(html).toBe(
        '<ul><li>parent</li><ul><li>child</li><ul><li>grandchild</li></ul></ul></ul>',
      );
    });

    it('handles switching from ul to ol cleanly', () => {
      const html = renderMarkdown('- bullet\n1. numbered');
      expect(html).toBe('<ul><li>bullet</li></ul><ol><li>numbered</li></ol>');
    });

    it('handles switching from ol to ul cleanly', () => {
      const html = renderMarkdown('1. numbered\n- bullet');
      expect(html).toBe('<ol><li>numbered</li></ol><ul><li>bullet</li></ul>');
    });
  });

  describe('inline citation markers stripped from prose (2026-09-16)', () => {
    const SOURCES = [
      { url: 'https://docs.example.com/one', title: 'One' },
      { url: 'https://docs.example.com/two', title: 'Two' },
    ];

    it('removes a single marker, leaving the claim clean', () => {
      const html = renderMarkdown('According to research [1].', SOURCES);
      expect(html).toBe('<p>According to research.</p>');
    });

    it('removes adjacent markers without leaving a gap', () => {
      const html = renderMarkdown('Multiple claims [1][2].', SOURCES);
      expect(html).toBe('<p>Multiple claims.</p>');
    });

    it('removes many spaced markers without a double space before punctuation', () => {
      const many = Array.from({ length: 7 }, (_, i) => ({
        url: `https://docs.example.com/${i + 1}`,
        title: `Source ${i + 1}`,
      }));
      const html = renderMarkdown('... course commencement [3] [4] [6] [7].', many);
      expect(html).toBe('<p>... course commencement.</p>');
    });

    it('keeps one separator between words when a marker sits mid-sentence', () => {
      const html = renderMarkdown('See [1] and [2] for details.', SOURCES);
      expect(html).toBe('<p>See and for details.</p>');
    });

    it('settles split-token deltas, stripping the marker once it completes', () => {
      const render = (content: string) => renderMarkdown(content, SOURCES);
      expect(render('See the pricing [')).toBe('<p>See the pricing [</p>');
      expect(render('See the pricing [2')).toBe('<p>See the pricing [2</p>');
      expect(render('See the pricing [2]')).toBe('<p>See the pricing</p>');
      expect(render('See the pricing [2] now.')).toBe('<p>See the pricing now.</p>');
    });

    it('ends identically to the completed answer across streamed frames', () => {
      const final = 'See the pricing [3] and check [2].';
      const frames = [
        'See the pricing [',
        'See the pricing [3',
        'See the pricing [3]',
        'See the pricing [3] and check [',
        'See the pricing [3] and check [2]',
        'See the pricing [3] and check [2].',
      ];
      // Once the last token streams, the surfaced frame renders exactly like
      // the final answer: in-range [2] stripped, out-of-range [3] literal.
      expect(renderMarkdown(frames[frames.length - 1], SOURCES)).toBe(
        renderMarkdown(final, SOURCES),
      );
    });

    it('leaves out-of-range markers as literal text', () => {
      const html = renderMarkdown('Out of bounds [99].', SOURCES);
      expect(html).not.toContain('wc-citation');
      expect(html).toContain('[99]');
    });

    it('leaves arr[1] in inline code as literal text', () => {
      const html = renderMarkdown('Check `arr[1]` index.', SOURCES);
      expect(html).toContain('<code>arr[1]</code>');
    });

    it('leaves [1] inside fenced code blocks as literal text', () => {
      const html = renderMarkdown('```\n[1]\n```', SOURCES);
      expect(html).toContain('[1]');
    });

    it('keeps markdown links intact when citation markers surround them', () => {
      const html = renderMarkdown(
        'See [1] and [docs](https://example.com/a) for details [2].',
        SOURCES,
      );
      expect(html).toBe(
        '<p>See and <a href="https://example.com/a" target="_blank" rel="noopener noreferrer">docs</a> for details.</p>',
      );
    });

    it('sanitizes malicious script in citation brackets', () => {
      const html = renderMarkdown('Attack [<script>1</script>].', SOURCES);
      expect(html).not.toContain('<script');
      expect(html).not.toContain('wc-citation');
    });

    it('keeps markers literal when no sources are present', () => {
      const html = renderMarkdown('As noted [1].');
      expect(html).toBe('<p>As noted [1].</p>');
    });
  });

  describe('trailing synthetic sources block suppression (Phase 2)', () => {
    const SOURCES = [
      { url: 'https://example.com/1', title: 'Source 1' },
      { url: 'https://example.com/2', title: 'Source 2' },
    ];

    it('removes trailing Sources: list when native sources exist', () => {
      const input = [
        'Undergraduate programs:',
        '1. BBA [1]',
        '2. BCA [2]',
        '',
        'Sources:',
        '1. [1]',
        '2. [2]',
      ].join('\n');
      const html = renderMarkdown(input, SOURCES);
      expect(html).toContain('BBA');
      expect(html).toContain('BCA');
      expect(html).not.toContain('Sources');
      expect(html).not.toMatch(/1\.\s*\[1\]/);
    });

    it('removes ### Sources variant when native sources exist', () => {
      const input = [
        'Undergraduate programs:',
        '1. BBA [1]',
        '',
        '### Sources',
        '- [1] https://example.com/1',
      ].join('\n');
      const html = renderMarkdown(input, SOURCES);
      expect(html).toContain('BBA');
      expect(html).not.toContain('Sources');
    });

    it('preserves legitimate mid-answer "Sources" text', () => {
      const input = 'Primary sources of energy include solar and wind power.';
      const html = renderMarkdown(input, SOURCES);
      expect(html).toContain('Primary sources of energy include solar and wind power.');
    });

    it('preserves original text when sources are absent or empty', () => {
      const input = ['Programs:', '1. BBA', '', 'Sources:', '1. [1]'].join('\n');
      const html = renderMarkdown(input, []);
      expect(html).toContain('Sources:');
    });
  });

  describe('streaming stability & incomplete markdown (Phase 2)', () => {
    it('handles incomplete bold syntax during streaming', () => {
      const html = renderMarkdown('**in-progress');
      expect(html).toBe('<p>**in-progress</p>');
    });

    it('handles incomplete inline code during streaming', () => {
      const html = renderMarkdown('`in-progress');
      expect(html).toBe('<p>`in-progress</p>');
    });

    it('handles incomplete fenced code during streaming', () => {
      const html = renderMarkdown('```js\nconst x = 1;');
      expect(html).toContain('<pre class="wc-code">');
      expect(html).toContain('const x = 1;');
      expect(html).toContain('</code></pre>');
    });

    it('handles incomplete table row during streaming', () => {
      const html = renderMarkdown('| Col 1 | Col 2 |\n| --- | --- |\n| Cell 1 |');
      expect(html).toContain('<div class="wc-table-scroll"><table>');
      expect(html).toContain('Cell 1');
      expect(html).toContain('</tbody></table></div>');
    });
  });
});

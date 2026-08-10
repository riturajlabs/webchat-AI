/**
 * Restricted markdown renderer (plan §4.1, ADR-004).
 *
 * Assistant output is model-generated (untrusted). A hand-rolled tokenizer
 * emits ONLY allowlisted constructs, then output passes through DOMPurify with
 * a locked-down config as a second gate. Raw HTML, images, autolinks and
 * dangerous URL schemes never reach the DOM.
 *
 * Phase 10 additions: GFM tables (with column alignment), nested lists,
 * strikethrough, and fenced code blocks with a language label + copy button.
 * The copy button is inert HTML (`class="wc-code-copy"`); the actual clipboard
 * wiring happens by event delegation in the UI layer so no inline handlers
 * ever enter the sanitized HTML.
 *
 * Deliberately tiny: the SDK ships no `marked`/`react-markdown` dependency
 * (ADR-008 bundle budget).
 */

import DOMPurify from 'dompurify';

// Everything the renderer may emit. Tags outside this set are dropped by the
// second-gate DOMPurify pass as defense-in-depth.
const ALLOWED_TAGS = [
  'p',
  'br',
  'strong',
  'em',
  'del',
  's',
  'code',
  'pre',
  'ul',
  'ol',
  'li',
  'blockquote',
  'h3',
  'h4',
  'h5',
  'h6',
  'a',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'button',
  'div',
  'span',
];

const ALLOWED_ATTR = ['href', 'rel', 'target', 'class', 'align'];

const SAFE_URL_PATTERN = /^(https?:\/\/|#|\/|[a-z0-9-]+\.)/i;
// https://html.spec.whatwg.org/multipage/parsing.html#data-state
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function isSafeUrl(href: string): boolean {
  if (
    !href ||
    href.startsWith('javascript:') ||
    href.startsWith('data:') ||
    href.startsWith('vbscript:')
  ) {
    return false;
  }
  return SAFE_URL_PATTERN.test(href);
}

/**
 * Render a line of inline markdown (bold / italic / strike / code / links) to
 * safe HTML.
 */
function renderInline(text: string): string {
  const tokens: string[] = [];
  let remaining = text;

  // Reject raw `<script>` (case-insensitive) outright even if not a tag pair.
  remaining = remaining.replace(/<script[\s\S]*?<\/script>/gi, '');

  const inlinePattern =
    /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(`([^`]+)`)|(~~([^~]+)~~)|(?<!!)(\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = inlinePattern.exec(remaining)) !== null) {
    const before = remaining.slice(lastIndex, match.index);
    if (before) {
      tokens.push(escapeHtml(before));
    }
    const [
      ,
      bold,
      boldText,
      italic,
      italicText,
      code,
      codeText,
      strike,
      strikeText,
      link,
      linkText,
      rawHref,
    ] = match;
    if (bold !== undefined) {
      tokens.push(`<strong>${escapeHtml(boldText)}</strong>`);
    } else if (italic !== undefined) {
      tokens.push(`<em>${escapeHtml(italicText)}</em>`);
    } else if (code !== undefined) {
      tokens.push(`<code>${escapeHtml(codeText)}</code>`);
    } else if (strike !== undefined) {
      tokens.push(`<del>${escapeHtml(strikeText)}</del>`);
    } else if (link !== undefined) {
      const href = rawHref.trim();
      if (isSafeUrl(href)) {
        tokens.push(
          `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(linkText)}</a>`,
        );
      } else {
        // Dangerous scheme: drop the link, keep the text escaped.
        tokens.push(escapeHtml(linkText));
      }
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < remaining.length) {
    tokens.push(escapeHtml(remaining.slice(lastIndex)));
  }
  return tokens.join('');
}

/** Split a GFM pipe row into its cells (leading/trailing pipes dropped). */
function splitRow(text: string): string[] {
  return text
    .split('|')
    .slice(1, -1)
    .map((cell) => cell.trim());
}

/** True when `text` is a table delimiter row like `| :--- | ---: |`. */
function isDelimiterRow(text: string): boolean {
  const cells = text
    .split('|')
    .slice(1, -1)
    .map((cell) => cell.trim());
  return cells.length > 0 && cells.every((cell) => /^:?-{1,}:?$/.test(cell));
}

/** Parse the delimiter row's per-column alignment. */
function delimiterAlign(text: string): Array<'left' | 'center' | 'right' | null> {
  return text
    .split('|')
    .slice(1, -1)
    .map((cell) => cell.trim())
    .map((cell) => {
      if (cell.startsWith(':') && cell.endsWith(':')) {
        return 'center';
      }
      if (cell.endsWith(':')) {
        return 'right';
      }
      if (cell.startsWith(':')) {
        return 'left';
      }
      return null;
    });
}

function alignAttr(align: 'left' | 'center' | 'right' | null): string {
  return align ? ` align="${align}"` : '';
}

interface ListFrame {
  indent: number;
  tag: 'ul' | 'ol';
}

function leadingSpaces(line: string): number {
  const match = line.match(/^ */);
  return match ? match[0].length : 0;
}

const CODE_HEADER_CLOSE = '</div>';

/**
 * Render markdown to sanitized HTML. Returns a string safe to inject into the
 * shadow DOM.
 */
export function renderMarkdown(source: string): string {
  if (!source) {
    return '';
  }

  const lines = source.split('\n');
  const parts: string[] = [];
  const listStack: ListFrame[] = [];

  let inFence = false;
  let inTable = false;
  let tableAlign: Array<'left' | 'center' | 'right' | null> = [];

  const closeAllLists = (): void => {
    while (listStack.length) {
      parts.push(`</${listStack.pop()!.tag}>`);
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    // --- Fenced code -------------------------------------------------------
    if (/^```/.test(trimmed)) {
      if (inFence) {
        parts.push('</code></pre>');
        inFence = false;
      } else {
        closeAllLists();
        const lang = trimmed.slice(3).trim();
        const langLabel = lang ? `<span class="wc-code-lang">${escapeHtml(lang)}</span>` : '';
        parts.push(
          `<pre class="wc-code"><div class="wc-code-header">${langLabel}` +
            '<button type="button" class="wc-code-copy" aria-label="Copy code">Copy</button>' +
            `${CODE_HEADER_CLOSE}<code>`,
        );
        inFence = true;
      }
      continue;
    }
    if (inFence) {
      parts.push(escapeHtml(line) + '\n');
      continue;
    }

    // --- Tables ------------------------------------------------------------
    if (!inTable && trimmed.startsWith('|') && isDelimiterRow(lines[i + 1]?.trim() ?? '')) {
      closeAllLists();
      const header = splitRow(trimmed);
      tableAlign = delimiterAlign(lines[i + 1].trim());
      parts.push('<table><thead><tr>');
      for (let c = 0; c < header.length; c += 1) {
        parts.push(`<th${alignAttr(tableAlign[c] ?? null)}>${renderInline(header[c])}</th>`);
      }
      parts.push('</tr></thead><tbody>');
      inTable = true;
      i += 1; // consume the delimiter row
      continue;
    }
    if (inTable) {
      if (trimmed.startsWith('|')) {
        parts.push('<tr>');
        const cells = splitRow(trimmed);
        for (let c = 0; c < cells.length; c += 1) {
          parts.push(`<td${alignAttr(tableAlign[c] ?? null)}>${renderInline(cells[c])}</td>`);
        }
        parts.push('</tr>');
        continue;
      }
      parts.push('</tbody></table>');
      inTable = false;
      tableAlign = [];
      // Fall through: the current line is a normal block.
    }

    // --- Lists (indent-aware, nested ul/ol) --------------------------------
    const listItem = trimmed.match(/^([-*+]|\d+\.)\s+(.+)$/);
    if (listItem) {
      const indent = leadingSpaces(line);
      const ordered = /^\d+\./.test(listItem[1]);
      const tag = ordered ? 'ol' : 'ul';

      while (listStack.length && listStack[listStack.length - 1].indent > indent) {
        parts.push(`</${listStack.pop()!.tag}>`);
      }
      const top = listStack[listStack.length - 1];
      if (!top) {
        listStack.push({ indent, tag });
        parts.push(`<${tag}>`);
      } else if (top.indent < indent) {
        listStack.push({ indent, tag });
        parts.push(`<${tag}>`);
      } else if (top.tag !== tag) {
        parts.push(`</${top.tag}>`);
        listStack[listStack.length - 1] = { indent, tag };
        parts.push(`<${tag}>`);
      }
      parts.push(`<li>${renderInline(listItem[2])}</li>`);
      continue;
    }
    closeAllLists();

    // --- Blockquote --------------------------------------------------------
    const quote = trimmed.match(/^>\s?(.*)$/);
    if (quote) {
      parts.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
      continue;
    }

    // --- Headings (# → h3 … #### → h6) -------------------------------------
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      parts.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }

    if (!trimmed) {
      continue;
    }
    parts.push(`<p>${renderInline(trimmed)}</p>`);
  }

  // Close anything still open at EOF.
  if (inFence) {
    parts.push('</code></pre>');
  }
  if (inTable) {
    parts.push('</tbody></table>');
  }
  closeAllLists();

  return DOMPurify.sanitize(parts.join(''), {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  });
}

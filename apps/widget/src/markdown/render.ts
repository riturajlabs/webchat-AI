/**
 * Restricted markdown renderer (plan §4.1, ADR-004).
 *
 * Assistant output is model-generated (untrusted). A hand-rolled tokenizer
 * emits ONLY allowlisted constructs, then output passes through DOMPurify with
 * a locked-down config as a second gate. Raw HTML, images, autolinks and
 * dangerous URL schemes never reach the DOM.
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
];

const ALLOWED_ATTR = ['href', 'rel', 'target'];

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
 * Render a line of inline markdown (bold / italic / code / links) to safe HTML.
 */
function renderInline(text: string): string {
  const tokens: string[] = [];
  let remaining = text;

  // Reject raw `<script>` (case-insensitive) outright even if not a tag pair.
  remaining = remaining.replace(/<script[\s\S]*?<\/script>/gi, '');

  const inlinePattern =
    /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(`([^`]+)`)|(?<!!)(\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = inlinePattern.exec(remaining)) !== null) {
    const before = remaining.slice(lastIndex, match.index);
    if (before) {
      tokens.push(escapeHtml(before));
    }
    const [, bold, boldText, italic, italicText, code, codeText, link, linkText, rawHref] = match;
    if (bold !== undefined) {
      tokens.push(`<strong>${escapeHtml(boldText)}</strong>`);
    } else if (italic !== undefined) {
      tokens.push(`<em>${escapeHtml(italicText)}</em>`);
    } else if (code !== undefined) {
      tokens.push(`<code>${escapeHtml(codeText)}</code>`);
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

function renderBlock(line: string): string {
  const trimmed = line.trim();

  // Headings #-#### → styled text (h3..h6; no raw h1/h2 semantics leak).
  const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (heading) {
    const level = Math.min(heading[1].length + 2, 6); // # → h3, ## → h4, …
    return `<h${level}>${renderInline(heading[2])}</h${level}>`;
  }

  // Fenced code block.
  const fence = trimmed.match(/^```\s*([^\s]*)/);
  if (fence) {
    return `<pre><code>${escapeHtml(line.slice(fence[0].length))}</code></pre>`;
  }

  // Blockquote.
  const quote = trimmed.match(/^>\s?(.*)$/);
  if (quote) {
    return `<blockquote>${renderInline(quote[1])}</blockquote>`;
  }

  // Unordered list item.
  const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
  if (unordered) {
    return `<li>${renderInline(unordered[1])}</li>`;
  }

  // Ordered list item.
  const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
  if (ordered) {
    return `<li>${renderInline(ordered[1])}</li>`;
  }

  if (!trimmed) {
    return '';
  }
  return `<p>${renderInline(trimmed)}</p>`;
}

/**
 * Render markdown to sanitized HTML. Returns a string safe to inject into the
 * shadow DOM.
 */
export function renderMarkdown(source: string): string {
  if (!source) {
    return '';
  }

  let html = '';
  let inFence = false;

  for (const line of source.split('\n')) {
    const trimmed = line.trim();
    if (/^```/.test(trimmed)) {
      inFence = !inFence;
      if (inFence) {
        html += '<pre><code>';
      } else {
        html += '</code></pre>';
      }
      continue;
    }
    if (inFence) {
      html += escapeHtml(line) + '\n';
      continue;
    }
    if (/^[-*+]\s+/.test(trimmed)) {
      if (!html.endsWith('<ul>') && !html.endsWith('<li>') && !html.endsWith('<ul>\n')) {
        html += '<ul>';
      }
      html += renderBlock(line);
      html += '\n';
    } else if (/^\d+\.\s+/.test(trimmed)) {
      if (!html.endsWith('<ol>') && !html.endsWith('<li>') && !html.endsWith('<ol>\n')) {
        html += '<ol>';
      }
      html += renderBlock(line);
      html += '\n';
    } else {
      if (/<ul>$/.test(html) || /<ol>$/.test(html)) {
        html += '</ul>';
      }
      html += renderBlock(line);
    }
  }

  if (inFence) {
    html += '</code></pre>';
  }

  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  });
}

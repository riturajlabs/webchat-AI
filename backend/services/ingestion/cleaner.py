"""HTML cleaning: strip boilerplate and return readable page text (Phase 4).

Removes scripts/styles/forms/embeds and navigation, header, footer, aside, plus
any element whose id/class hints at ads, social widgets, or cookie banners -
then collapses whitespace. This is the text that becomes a `documents` row and
the Phase 5 chunking/embedding input.

Structure preservation (audit R-07/R-08): tables are rendered as readable
markdown-style rows (`| a | b |`), `<pre>` blocks keep their verbatim layout
(indentation and internal newlines), and headings are emitted as markdown-style
`#` lines so the chunker can carry the nearest heading into chunk metadata.
Normal text keeps the existing behavior: inline runs collapse to single
spaces, boilerplate/footers are stripped, repeated lines deduped.
"""

import re

from bs4 import BeautifulSoup, Comment
from bs4.element import NavigableString, Tag

# Tags that carry no page content (00-AI-Development-Rules: safe HTML only).
_BOILERPLATE_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "nav",
    "header",
    "footer",
    "aside",
)

# id/class markers for ads, social and consent chrome that leak into text.
_BOILERPLATE_MARKERS = (
    "advert",
    "adsense",
    "banner",
    "sponsor",
    "promo",
    "social",
    "share",
    "newsletter",
    "cookie",
    "consent",
    "gdpr",
    "popup",
    "modal",
    "menu",
    "sidebar",
    "breadcrumb",
    "paywall",
    "sticky",
    "floating",
    "related",
    "recommend",
    "copyright",
    "disclaimer",
    "legal",
    "footer-",
    "site-footer",
    "site-header",
)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# Block-level boundaries: normal text still collapses to single spaces within
# a block, but blocks separate with newlines so tables/pre/headings keep their
# structure and the footer filter works per line instead of on the whole page.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "section",
        "table",
        "ul",
    }
) | set(_HEADING_TAGS)

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")

# Common legal/footer boilerplate lines that survive markup removal.
_FOOTER_LINE_RE = re.compile(
    r"(?:©\s*|&copy;)|(?:all rights reserved)|(?:privacy policy)|(?:terms of service)|"
    r"(?:cookie policy)|(?:powered by)|(?:sitemap)",
    re.IGNORECASE,
)


def _collapse(value: str) -> str:
    """Collapse inline whitespace runs to single spaces (never touches \\n)."""
    return _WHITESPACE.sub(" ", value)


def _inline_text(tag: Tag) -> str:
    """Whitespace-collapsed one-line text of `tag`'s contents."""
    return _collapse(tag.get_text(" ", strip=True)).strip()


def _render_table(table: Tag) -> str:
    """Render a <table> as readable markdown-style rows (audit R-07)."""
    lines: list[str] = []
    for row in table.find_all("tr"):
        cells = [_inline_text(cell) for cell in row.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if cells:
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _serialize(node: Tag | NavigableString, out: list[str]) -> None:
    """Depth-first serializer keeping tables/pre/headings structurally intact.

    Inline text accumulates as collapsed fragments; block boundaries flush a
    newline so each logical block lands on its own line(s). `<pre>` content is
    appended verbatim - its indentation and internal newlines must survive the
    global whitespace pass untouched.
    """
    if isinstance(node, NavigableString):
        text = _collapse(str(node))
        if text.strip():
            out.append(text)
        return
    name = node.name or ""
    if name == "pre":
        # Verbatim block: leading/trailing blank edges trimmed, interior kept.
        raw = node.get_text().strip("\n")
        out.append("\n" + raw.rstrip() + "\n")
        return
    if name == "table":
        rendered = _render_table(node)
        if rendered:
            out.append("\n" + rendered + "\n")
        return
    if name == "br":
        out.append("\n")
        return
    if name in _HEADING_TAGS:
        text = _inline_text(node)
        if text:
            level = int(name[1]) if name[1].isdigit() else 1
            out.append("\n" + "#" * level + " " + text + "\n")
        return
    for child in node.children:
        _serialize(child, out)  # type: ignore[arg-type]
    if name in _BLOCK_TAGS:
        out.append("\n")


def clean_html(html: str, *, max_chars: int = 200_000) -> str:
    """Return cleaned, de-boilerplated text for `html`, capped at `max_chars`."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(_BOILERPLATE_TAGS):
        tag.decompose()

    for tag in soup.find_all(True):
        if tag.parent is None:
            continue
        raw_classes = tag.get("class")
        classes = " ".join(str(c) for c in raw_classes) if raw_classes else ""
        ident = str(tag.get("id") or "").lower()
        if any(marker in f"{classes} {ident}" for marker in _BOILERPLATE_MARKERS):
            tag.decompose()

    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    fragments: list[str] = []
    _serialize(main, fragments)
    text = _BLANK_LINES.sub("\n", "".join(fragments)).strip()

    lines = [line for line in text.split("\n") if line.strip() and not _FOOTER_LINE_RE.search(line)]
    text = "\n".join(_dedupe_repeated_lines(lines))
    return text[:max_chars]


def _dedupe_repeated_lines(lines: list[str]) -> list[str]:
    """Drop lines that repeat across the page (repeated footer/nav leftovers).

    A phrase (e.g. a menu label, phone number, or footer tagline) that appears
    more than 3 times is boilerplate rather than content; keep one copy so the
    surrounding text still reads naturally.
    """
    counts: dict[str, int] = {}
    for line in lines:
        key = line.strip().casefold()
        counts[key] = counts.get(key, 0) + 1
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        key = line.strip().casefold()
        if counts[key] > 3:
            if key in seen:
                continue
            seen.add(key)
        result.append(line)
    return result


__all__ = ["clean_html"]

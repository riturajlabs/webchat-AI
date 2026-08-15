"""HTML cleaning: strip boilerplate and return readable page text (Phase 4).

Removes scripts/styles/forms/embeds and navigation, header, footer, aside, plus
any element whose id/class hints at ads, social widgets, or cookie banners -
then collapses whitespace. This is the text that becomes a `documents` row and
the Phase 5 chunking/embedding input.
"""

import re

from bs4 import BeautifulSoup, Comment

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

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")

# Common legal/footer boilerplate lines that survive markup removal.
_FOOTER_LINE_RE = re.compile(
    r"(?:©\s*|&copy;)|(?:all rights reserved)|(?:privacy policy)|(?:terms of service)|"
    r"(?:cookie policy)|(?:powered by)|(?:sitemap)",
    re.IGNORECASE,
)


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
    text = main.get_text(" ", strip=True)
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n", text).strip()

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

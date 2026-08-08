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
    "popup",
    "modal",
    "menu",
    "sidebar",
)

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


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
    return text[:max_chars]

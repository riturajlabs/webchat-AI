"""Structured content extraction from crawled HTML (docs/06, Phase 4).

Uses BeautifulSoup's stdlib `html.parser` backend (no lxml build) to pull the
title, language, meta tags, canonical URL, headings, paragraphs, internal
links, and a representative preview image out of a rendered page.
"""

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from backend.utils.url_validator import normalize_crawl_url

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# Meta-image preference order (all Open Graph / embedded-card metadata the page
# advertises itself; `og` family before `twitter` so the richer card wins).
_META_IMAGE_KEYS = (
    "og:image",
    "og:image:secure_url",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
    "thumbnail",
)

# Lazy-loading attribute shims (many sites defer real image URLs into these).
_LAZY_IMG_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-actualsrc")

# Below this edge (px) an image is treated as a dot/icon, not content.
_MIN_IMG_EDGE = 40

# File-name fragments that identify tracking pixels, spacers and UI chrome
# rather than representative content. Matched against the basename (lowercased).
_IMG_JUNK_FRAGMENTS = (
    "pixel",
    "spacer",
    "1x1",
    "blank",
    "tracker",
    "transparent",
    "placeholder",
    "loading",
    "grey",
    "gray",
    "sprite",
)


@dataclass(frozen=True)
class ExtractedPage:
    """Structured view of one crawled page."""

    url: str
    title: str
    language: str
    meta: dict[str, str]
    canonical: str | None
    headings: list[str]
    paragraphs: list[str]
    links: list[str] = field(default_factory=list)


def extract_page(html: str, url: str) -> ExtractedPage:
    """Extract structured content from `html` (resolving links against `url`)."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    language = str(soup.html.get("lang") or "") if soup.html else ""

    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        if tag.get("name"):
            meta[str(tag["name"]).lower()] = str(tag.get("content") or "").strip()
        elif tag.get("property"):
            meta[str(tag["property"]).lower()] = str(tag.get("content") or "").strip()

    canonical_tag = soup.find("link", rel="canonical")
    canonical = str(canonical_tag.get("href")).strip() if canonical_tag else None

    headings = [tag.get_text(" ", strip=True) for tag in soup.find_all(_HEADING_TAGS)]
    paragraphs = [tag.get_text(" ", strip=True) for tag in soup.find_all("p")]

    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        normalized = normalize_crawl_url(str(tag["href"]), url)
        if normalized is not None and normalized not in links:
            links.append(normalized)

    return ExtractedPage(
        url=url,
        title=title,
        language=language,
        meta=meta,
        canonical=canonical,
        headings=headings,
        paragraphs=paragraphs,
        links=links,
    )


def _resolve_image_url(raw: str | None, page_url: str) -> str | None:
    """Resolve `raw` against `page_url` and keep only usable http(s) URLs.

    Relative and protocol-relative URLs are normalized against the page's own
    origin (post-redirect `page_url`). `data:`/`javascript:`/etc. are rejected
    as non-images, and a bare scheme-less string resolves to the page itself.
    """
    if not raw or not raw.strip():
        return None
    absolute = urljoin(page_url, raw.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return absolute


def _is_junk_image_url(url: str) -> bool:
    """True when the URL points at tracking/icon/spacer chrome, not content."""
    path = urlparse(url).path.lower()
    basename = path.rsplit("/", 1)[-1].split("?", 1)[0]
    return any(fragment in basename for fragment in _IMG_JUNK_FRAGMENTS)


def _int_attr(img: Tag, name: str) -> int | None:
    value = img.get(name)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _largest_srcset_raw(srcset: str | None) -> str | None:
    """Return the largest (or last) candidate URL from an `srcset` value."""
    if not srcset:
        return None
    candidates: list[tuple[str, int | None]] = []
    for part in srcset.split(","):
        tokens = part.split()
        if not tokens:
            continue
        width: int | None = None
        for token in tokens[1:]:
            if token.endswith("w"):
                try:
                    width = int(token[:-1])
                except ValueError:
                    width = None
        candidates.append((tokens[0], width))
    sized: list[tuple[str, int]] = []
    for url, width in candidates:
        if width is not None:
            sized.append((url, width))
    if sized:
        return max(sized, key=lambda candidate: candidate[1])[0]
    return candidates[-1][0]


def _pick_img_candidate_url(img: Tag, page_url: str) -> str | None:
    """Choose the best usable URL for one `<img>` tag.

    Priority: largest `srcset` variant -> `src` -> largest `data-srcset` ->
    lazy-loading shims (`data-src` etc.). A non-http `src` (e.g. a `data:`
    placeholder) is skipped in favour of a lazy real URL.
    """
    for attr in ("srcset", "data-srcset"):
        raw = img.get(attr)
        if isinstance(raw, str):
            raw = _largest_srcset_raw(raw)
        else:
            raw = None
        resolved = _resolve_image_url(raw, page_url) if raw else None
        if resolved is not None and not _is_junk_image_url(resolved):
            return resolved
    src = img.get("src")
    if isinstance(src, str) and src:
        resolved = _resolve_image_url(src, page_url)
        if resolved is not None and not _is_junk_image_url(resolved):
            return resolved
    for attr in _LAZY_IMG_ATTRS:
        lazy = img.get(attr)
        if not isinstance(lazy, str) or not lazy:
            continue
        resolved = _resolve_image_url(lazy, page_url)
        if resolved is not None and not _is_junk_image_url(resolved):
            return resolved
    return None


def _is_tiny_image(img: Tag) -> bool:
    """True when known attribute dimensions are below a content threshold."""
    width = _int_attr(img, "width")
    height = _int_attr(img, "height")
    return (width is not None and width < _MIN_IMG_EDGE) or (
        height is not None and height < _MIN_IMG_EDGE
    )


def _img_area(img: Tag) -> int:
    """Estimated pixel area for ranking; missing dimensions use a heuristic."""
    width = _int_attr(img, "width")
    height = _int_attr(img, "height")
    if width is not None and height is not None:
        return width * height
    if width is not None:
        return width * 480
    if height is not None:
        return 640 * height
    return 640 * 480


def _pick_best_img(soup: BeautifulSoup, page_url: str) -> str | None:
    """Pick the largest non-tiny, non-junk `<img>` in document order."""
    best: str | None = None
    best_area = -1
    for img in soup.find_all("img"):
        url = _pick_img_candidate_url(img, page_url)
        if url is None or _is_tiny_image(img):
            continue
        area = _img_area(img)
        if area > best_area:
            best = url
            best_area = area
    return best


def pick_preview_image(
    meta: dict[str, str],
    page_url: str,
    *,
    soup: BeautifulSoup | None = None,
) -> str | None:
    """Choose a website preview image for a crawled page, if any.

    Preference order: Open Graph / Twitter card metadata (the page's own
    declared image), then the best representative `<img>` (largest non-tiny,
    non-tracker image in document order, honouring `srcset` and lazy-loading
    shims), then the page's own same-origin `/favicon.ico` as a last resort.
    All candidates are URLs the page already advertises (never fetched here),
    so no new crawl/SSRF surface is introduced. Only http(s) URLs are accepted
    (data:/javascript:/etc. are skipped as non-images) and relative/protocol-
    relative URLs are normalized against the page's origin.

    When metadata declared an image but it is unusable, `None` is returned
    rather than silently substituting the favicon. When the page's `<img>`
    tags exist but every one is incremental junk (1×1 trackers, icons), `None`
    is returned too — only a page with no usable image *signal* at all falls
    back to the favicon. Callers that only have metadata (no soup) keep the
    historic meta->favicon behaviour.
    """
    found_key = next((key for key in _META_IMAGE_KEYS if key in meta), None)
    if found_key is not None:
        # A declared meta image: return it when usable, otherwise None (the
        # declaration is authoritative either way — don't fall to the favicon).
        return _resolve_image_url(meta[found_key], page_url)

    if soup is not None:
        found = _pick_best_img(soup, page_url)
        if found is not None:
            return found
        if soup.find("img") is not None:
            # Images exist but all are too small / junk: no meaningful preview.
            return None

    base = urlparse(page_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        return None
    return f"{base.scheme}://{base.netloc}/favicon.ico"

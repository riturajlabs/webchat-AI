"""Content-aware crawl candidate prioritization (Phase 2, ING-01).

The crawler's breadth-first frontier is ordered so likely content-rich pages are
fetched before navigation/hub pages. This module scores a not-yet-crawled URL
using structural signals available at discovery time (its URL path plus the
content/links of the page that linked to it), so none of the competing heuristics
are hard-coded to a specific documentation site — they generalize to ordinary
documentation websites.

Only the *ordering* of the crawl frontier changes. The traversal still enforces
`crawl_max_pages`, `crawl_max_depth`, domain/robots/SSRF restrictions and URL
normalization, and it never discards a hub page: a lower-scoring hub is simply
deferred until the content-rich pages it links to have been crawled.
"""

from urllib.parse import urlparse

# Extension on a URL path that typically marks a document (leaf) rather than a
# navigation index or hub.
_LEAF_EXTENSIONS = frozenset(
    {".html", ".htm", ".xhtml", ".md", ".php", ".asp", ".aspx", ".jsp", ".cgi"}
)

# Generic content-bearing path tokens: a page in one of these sections is far
# more likely to be tutorial/reference/how-to material worth embedding.
_CONTENT_TOKENS = frozenset(
    {
        "api",
        "examples",
        "faq",
        "features",
        "getting-started",
        "glossary",
        "guide",
        "howto",
        "intro",
        "learn",
        "manual",
        "overview",
        "quickstart",
        "reference",
        "tutorial",
        "usage",
    }
)

# Navigation / index / version-landing path tokens: pages here are usually hub,
# index, archive, or download listings that link out rather than carry content.
_NAV_HUB_TOKENS = frozenset(
    {
        "archive",
        "archives",
        "blog",
        "changelog",
        "documentation",
        "download",
        "genindex",
        "home",
        "index",
        "news",
        "release",
        "releases",
        "version",
    }
)

# A parent page with at least this many outbound links and less than this much
# cleaned text is treated as a link-dense hub: its children are dampened because
# they are more likely to be navigation than leaf content.
_LINK_DENSE_THRESHOLD = 60
_CONTENT_RICH_THRESHOLD = 800

_BASE_HUB_PENALTY = 3
_BASE_LEAF_BONUS = 2
_DEPTH_BONUS = 2
_DEEP_PATH_PENALTY = 1


def score_crawl_candidate(
    url: str,
    *,
    depth: int,
    max_depth: int,
    link_density: int | None = None,
    content_length: int | None = None,
) -> int:
    """Return a structural content-richness score for a not-yet-crawled URL.

    Higher = more likely to be crawled first. The score drives the frontier's
    priority ordering only; ties break toward lower depth then earlier
    discovery, so the traversal stays deterministic and BFS-like.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    segments = [segment for segment in path.split("/") if segment]
    lower = path.lower()

    score = 0

    # Path depth from the root. Two-to-four-segment paths are typical leaf /
    # section content; the root and one-segment paths are hub/landing, and very
    # deep paths grow increasingly likely to be archives or non-content.
    if 2 <= len(segments) <= 4:
        score += _DEPTH_BONUS
    elif len(segments) <= 1:
        score -= _BASE_HUB_PENALTY
    elif len(segments) > 6:
        score -= _DEEP_PATH_PENALTY

    # A file extension implies a document (leaf); a trailing slash on a
    # non-root path implies a section index or hub.
    if any(path.endswith(ext) for ext in _LEAF_EXTENSIONS):
        score += _BASE_LEAF_BONUS
    elif path != "/" and parsed.path.endswith("/"):
        score -= 1

    # Generic content-bearing path tokens: strong positive.
    if any(token in lower for token in _CONTENT_TOKENS):
        score += _BASE_LEAF_BONUS + 1

    # Navigation / index / archive / version-landing tokens: strong negative.
    if any(token in lower for token in _NAV_HUB_TOKENS):
        score -= _BASE_HUB_PENALTY

    # A link-dense, thin parent is a hub: its children are more likely navigational.
    if (
        link_density is not None
        and content_length is not None
        and link_density >= _LINK_DENSE_THRESHOLD
        and content_length < _CONTENT_RICH_THRESHOLD
    ):
        score -= 1

    # Penalize re-entering depth: deeper pages cost more of the page budget, so
    # prefer the shallower content when everything else is equal.
    if depth > max_depth // 2:
        score -= 1

    return score


__all__ = ["score_crawl_candidate"]

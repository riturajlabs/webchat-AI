"""Unit tests for HTML extraction (Phase 4 ingestion)."""

from backend.services.ingestion import extract_page, pick_preview_image

HOME = """<!doctype html>
<html lang="en-GB">
<head>
  <title>Acme Ltd</title>
  <meta name="description" content="Acme helps teams.">
  <meta property="og:title" content="Acme Ltd">
  <link rel="canonical" href="https://acme.example/home">
</head>
<body>
  <main>
    <h1>Welcome</h1>
    <h2>What we do</h2>
    <p>We build tools.</p>
    <p>We ship daily.</p>
    <a href="/about">About</a>
    <a href="https://acme.example/about?utm_source=x#top">Tracked</a>
    <a href="https://external.example/away">External</a>
    <a href="mailto:hi@acme.example">Mail</a>
  </main>
</body>
</html>"""


def test_extracts_title_language_and_canonical() -> None:
    page = extract_page(HOME, "https://acme.example/")
    assert page.title == "Acme Ltd"
    assert page.language == "en-GB"
    assert page.canonical == "https://acme.example/home"


def test_extracts_meta_tags() -> None:
    page = extract_page(HOME, "https://acme.example/")
    assert page.meta["description"] == "Acme helps teams."
    assert page.meta["og:title"] == "Acme Ltd"


def test_extracts_headings_and_paragraphs() -> None:
    page = extract_page(HOME, "https://acme.example/")
    assert page.headings == ["Welcome", "What we do"]
    assert page.paragraphs == ["We build tools.", "We ship daily."]


def test_extracts_normalized_internal_links_only() -> None:
    page = extract_page(HOME, "https://acme.example/")
    # Links are resolved to normalized absolute URLs (fragments stripped,
    # tracking params removed); non-http(s) links are dropped.
    assert "https://acme.example/about" in page.links
    assert "mailto:hi@acme.example" not in page.links
    assert "https://external.example/away" in page.links


def test_empty_document_yields_empty_fields() -> None:
    page = extract_page("", "https://acme.example/")
    assert page.title == ""
    assert page.headings == []
    assert page.paragraphs == []
    assert page.links == []


def test_pick_preview_image_prefers_og_over_twitter() -> None:
    meta = {"og:image": "https://cdn.example/og.png", "twitter:image": "https://cdn.example/tw.png"}
    assert pick_preview_image(meta, "https://acme.example/") == "https://cdn.example/og.png"


def test_pick_preview_image_falls_back_to_twitter() -> None:
    meta = {"twitter:image": "https://cdn.example/tw.png"}
    assert pick_preview_image(meta, "https://acme.example/") == "https://cdn.example/tw.png"


def test_pick_preview_image_normalizes_relative_url() -> None:
    meta = {"og:image": "/og.png"}
    assert pick_preview_image(meta, "https://acme.example/") == "https://acme.example/og.png"


def test_pick_preview_image_rejects_non_http() -> None:
    assert (
        pick_preview_image({"og:image": "data:image/png;base64,xx"}, "https://acme.example/")
        is None
    )
    assert pick_preview_image({"og:image": "javascript:alert(1)"}, "https://acme.example/") is None


def test_pick_preview_image_falls_back_to_same_origin_favicon() -> None:
    assert (
        pick_preview_image({}, "https://acme.example/some/page")
        == "https://acme.example/favicon.ico"
    )
    assert (
        pick_preview_image({}, "http://acme.example:8080/")
        == "http://acme.example:8080/favicon.ico"
    )
    # No usable origin (not http(s)) → still none, never a broken URL.
    assert pick_preview_image({}, "ftp://acme.example/") is None

"""Unit tests for HTML extraction (Phase 4 ingestion)."""

from backend.services.ingestion import extract_page

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

"""Unit tests for HTML content cleaning (Phase 4 ingestion)."""

from backend.services.ingestion import clean_html

DIRTY = """<!doctype html>
<html><body>
  <nav>Menu: <a href="/">Home</a></nav>
  <script>alert('x');</script>
  <style>.x{}</style>
  <aside class="ad-banner">Buy now</aside>
  <div id="newsletter-signup">Subscribe!</div>
  <main>
    <h1>Real content</h1>
    <p>    This   is   spaced    out.   </p>
    <p>Second paragraph.</p>
  </main>
  <footer>Copyright</footer>
</body></html>"""


def test_removes_boilerplate_tags_and_markers() -> None:
    text = clean_html(DIRTY)
    assert "Menu" not in text
    assert "alert('x')" not in text
    assert "Buy now" not in text
    assert "Subscribe" not in text
    assert "Copyright" not in text


def test_keeps_main_content() -> None:
    text = clean_html(DIRTY)
    assert "Real content" in text
    assert "Second paragraph." in text


def test_collapses_whitespace() -> None:
    text = clean_html(DIRTY)
    assert "This is spaced out." in text


def test_truncates_to_max_chars() -> None:
    long_html = "<p>" + "word " * 1000 + "</p>"
    text = clean_html(long_html, max_chars=100)
    assert len(text) == 100


def test_empty_input_yields_empty_text() -> None:
    assert clean_html("") == ""
    assert clean_html("<html><body></body></html>") == ""

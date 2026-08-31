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


# ---------------------------------------------------------------------------
# Structure preservation (audit R-07) + heading markers (audit R-08)
# ---------------------------------------------------------------------------

TABLE_HTML = """<!doctype html><html><body><main>
  <h2>Pricing</h2>
  <p>Choose a plan below.</p>
  <table>
    <tr><th>Plan</th><th>Price</th></tr>
    <tr><td>Starter</td><td>$9</td></tr>
    <tr><td>Pro</td><td>$19</td></tr>
  </table>
</main></body></html>"""

CODE_HTML = """<!doctype html><html><body><main>
  <p>Install like this:</p>
  <pre>
  npm install acme
      cd acme && ./setup.sh
  </pre>
</main></body></html>"""


def test_table_becomes_readable_markdown_rows() -> None:
    text = clean_html(TABLE_HTML)

    # Header row and data rows keep cell structure on single lines.
    assert "| Plan | Price |" in text
    assert "| Starter | $9 |" in text
    assert "| Pro | $19 |" in text


def test_table_cells_do_not_run_together() -> None:
    """Cell values must not blur into surrounding prose."""
    text = clean_html(TABLE_HTML)
    assert "Plan Price Starter" not in text.replace("|", "")
    assert "Choose a plan below." in text


def test_pre_block_preserves_layout_and_indentation() -> None:
    text = clean_html(CODE_HTML)

    assert "npm install acme" in text
    # Interior indentation and line structure survive cleaning verbatim.
    assert "    cd acme && ./setup.sh" in text
    assert "npm install acme\n" in text


def test_headings_are_marked_for_chunk_metadata() -> None:
    """h1-h6 become markdown-style heading lines (audit R-08 input)."""
    text = clean_html(TABLE_HTML)
    assert "## Pricing" in text

    headed = "<main><h1>Guide</h1><p>Body.</p><h3>Details</h3><p>More.</p></main>"
    cleaned = clean_html(headed)
    assert "# Guide" in cleaned
    assert "### Details" in cleaned


def test_normal_text_behavior_unchanged() -> None:
    """Non-table/pre content keeps the established cleaning semantics."""
    text = clean_html(DIRTY)
    assert "Real content" in text
    assert "This is spaced out." in text
    assert "Menu" not in text

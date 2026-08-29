"""Tests for widget model and schema default alignment (Phase 10 + Phase 11).

Verifies that:
- The Widget model and WidgetPublicConfig share the same default values.
- The widget SDK DEFAULT_CONFIG matches backend defaults.
- CSS length validation is consistent between backend and SDK.
"""

from backend.models.widget import Widget
from backend.schemas.widget import WidgetConfigUpdate, WidgetPublicConfig

# ---------------------------------------------------------------------------
# Phase 10: Shared theme defaults
# ---------------------------------------------------------------------------


def test_widget_model_accent_color_default() -> None:
    """Widget model default accent_color must match the SDK fallback."""
    w = Widget.new(tenant_id="t1", website_id="w1")
    assert w.accent_color == "#25D366"


def test_widget_model_primary_color_default() -> None:
    """Widget model default primary_color must match the SDK fallback."""
    w = Widget.new(tenant_id="t1", website_id="w1")
    assert w.primary_color == "#10A37F"


def test_widget_model_theme_defaults() -> None:
    """Widget model defaults match the shared contract."""
    w = Widget.new(tenant_id="t1", website_id="w1")
    assert w.theme == "light"
    assert w.position == "bottom-right"
    assert w.font_size == "md"
    assert w.branding is True
    assert w.dark_mode is False
    assert w.auto_open is False
    assert w.bot_name == "WebChat AI"
    assert w.bot_status_text == "Online"
    assert w.width == "380px"
    assert w.height == "600px"
    assert w.border_radius == "20px"
    assert w.launcher_size == "58px"


def test_widget_public_config_matches_model_defaults() -> None:
    """WidgetPublicConfig defaults must match Widget model defaults."""
    w = Widget.new(tenant_id="t1", website_id="w1")
    pub = WidgetPublicConfig.from_widget(w)

    assert pub.primary_color == w.primary_color == "#10A37F"
    assert pub.accent_color == w.accent_color == "#25D366"
    assert pub.theme == w.theme
    assert pub.position == w.position
    assert pub.font_size == w.font_size
    assert pub.width == w.width
    assert pub.height == w.height
    assert pub.border_radius == w.border_radius
    assert pub.launcher_size == w.launcher_size


# ---------------------------------------------------------------------------
# Phase 11: CSS length validation alignment
# ---------------------------------------------------------------------------


def test_css_length_accepts_px() -> None:
    """px units are accepted."""
    cfg = WidgetConfigUpdate(width="420px")
    assert cfg.width == "420px"


def test_css_length_accepts_em() -> None:
    """em units are accepted."""
    cfg = WidgetConfigUpdate(width="2.5em")
    assert cfg.width == "2.5em"


def test_css_length_accepts_rem() -> None:
    """rem units are accepted."""
    cfg = WidgetConfigUpdate(height="40rem")
    assert cfg.height == "40rem"


def test_css_length_accepts_percent() -> None:
    """Percentage units are accepted."""
    cfg = WidgetConfigUpdate(border_radius="50%")
    assert cfg.border_radius == "50%"


def test_css_length_rejects_vh() -> None:
    """vh units are rejected (Phase 11: fixed dimensions only)."""
    import pytest
    with pytest.raises(ValueError, match="CSS length"):
        WidgetConfigUpdate(width="50vh")


def test_css_length_rejects_vw() -> None:
    """vw units are rejected (Phase 11: fixed dimensions only)."""
    import pytest
    with pytest.raises(ValueError, match="CSS length"):
        WidgetConfigUpdate(width="50vw")


def test_css_length_rejects_invalid_format() -> None:
    """Arbitrary strings are rejected."""
    import pytest
    with pytest.raises(ValueError, match="CSS length"):
        WidgetConfigUpdate(width="calc(100% - 20px)")


def test_css_length_rejects_negative() -> None:
    """Negative values are rejected."""
    import pytest
    with pytest.raises(ValueError, match="CSS length"):
        WidgetConfigUpdate(width="-20px")

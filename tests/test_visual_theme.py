"""Contratos del sistema visual Broadcast moderno."""

import importlib.util

import pytest

from ui import palette, style


def test_broadcast_theme_exposes_three_distinct_surface_levels():
    """Evita volver a una interfaz plana con un único fondo."""
    assert hasattr(palette, "BG_CARD")
    assert len({palette.BG_ROOT, palette.BG_PANEL, palette.BG_CARD}) == 3


def test_invalid_accent_falls_back_without_breaking_style_generation():
    """Un valor corrupto en preferencias no debe impedir el arranque."""
    assert hasattr(style, "normalize_accent")
    assert style.normalize_accent("not-a-color") == style.DEFAULT_ACCENT
    assert style.normalize_accent(None) == style.DEFAULT_ACCENT
    assert style.DEFAULT_ACCENT in style.build_style("not-a-color")


def test_extreme_accents_choose_readable_foreground():
    """Los botones siguen siendo legibles con blanco o negro personalizados."""
    assert style.accent_shades("#ffffff")["on_accent"] == palette.BG_ROOT
    assert style.accent_shades("#000000")["on_accent"] == "#ffffff"


def _luminance(hexcolor: str) -> float:
    values = []
    for start in (1, 3, 5):
        channel = int(hexcolor[start:start + 2], 16) / 255.0
        values.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("accent", style.ACCENT_PRESETS.values())
def test_every_accent_preset_gets_at_least_aa_text_contrast(accent):
    shades = style.accent_shades(accent)
    assert _contrast(shades["base"], shades["on_accent"]) >= 4.5


def test_user_accent_does_not_replace_semantic_colors():
    """Grabación, casting y temporizador conservan su significado visual."""
    qss = style.build_style("#ff00ff")
    assert palette.DANGER in qss
    assert palette.ACCENT_CAST in qss
    assert palette.ACCENT_SLEEP in qss


def test_visual_variant_module_is_available():
    """Las pantallas deben compartir un helper en lugar de QSS local repetido."""
    assert importlib.util.find_spec("ui.visual") is not None


def test_visual_variant_falls_back_and_updates_widget(qapp):
    """Una variante desconocida degrada al estilo base sin excepción."""
    from PySide6.QtWidgets import QWidget
    from ui.visual import set_variant, set_visual_state

    widget = QWidget()
    assert set_variant(widget, "desconocida") == "default"
    assert widget.property("uiVariant") == "default"
    assert set_visual_state(widget, "error") == "error"
    assert widget.property("uiState") == "error"
    widget.deleteLater()

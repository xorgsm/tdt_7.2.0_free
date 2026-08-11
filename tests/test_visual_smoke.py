"""Smoke tests y capturas del tema Broadcast moderno."""

from pathlib import Path

import pytest
from PySide6.QtTest import QTest

from core import config as cfg
from ui import main_window as main_window_module
from ui import torrent_panel as torrent_panel_module
from ui.dialogs import SettingsDialog
from ui.main_window import MainWindow, NAV_DOWNLOAD, NAV_HOME, NAV_RADIO, NAV_TV
from ui.style import ACCENT_PRESETS, build_style


@pytest.fixture
def broadcast_window(qapp, monkeypatch):
    settings = cfg.DEFAULT_SETTINGS.copy()
    settings.update({"epg_url": "", "onboarding_shown": True})
    monkeypatch.setattr(main_window_module.cfg, "load_settings", lambda: settings.copy())
    monkeypatch.setattr(MainWindow, "_load_tv_channels", lambda self, force=False: None)
    monkeypatch.setattr(MainWindow, "_load_radio_stations", lambda self, force=False: None)
    monkeypatch.setattr(main_window_module.SystemMediaKeys, "start", lambda self: False)
    monkeypatch.setattr(main_window_module.TrayReminderController, "setup", lambda self: None)
    monkeypatch.setattr(torrent_panel_module, "paquete_disponible", lambda: False)

    previous_style = qapp.styleSheet()
    qapp.setStyleSheet(build_style(settings["accent_color"]))
    window = MainWindow(activated=True)
    yield window
    window._is_closing = True
    window._media_keys.stop()
    window.deleteLater()
    qapp.processEvents()
    qapp.setStyleSheet(previous_style)


@pytest.mark.parametrize("size", [(1024, 640), (1440, 900), (1920, 1080)])
def test_main_window_layout_at_supported_sizes(qapp, broadcast_window, size):
    broadcast_window.resize(*size)
    broadcast_window.show()
    qapp.processEvents()
    assert broadcast_window.minimumWidth() <= size[0]
    assert broadcast_window.minimumHeight() <= size[1]
    assert all(value > 0 for value in broadcast_window.main_splitter.sizes())
    assert broadcast_window.content_widget.width() >= broadcast_window.content_widget.minimumWidth()


@pytest.mark.parametrize("accent", [*ACCENT_PRESETS.values(), "#ffffff", "#000000", "#ff00ff"])
def test_all_accent_presets_generate_complete_theme(accent):
    qss = build_style(accent)
    assert len(qss) > 5000
    assert "QFrame#homeHero" in qss
    assert "QProgressBar#mediaProgress" in qss
    assert "QDialog[uiSurface=\"dialog\"]" in qss


def test_home_labels_blend_into_hero_surface(qapp, broadcast_window):
    broadcast_window._on_nav_changed(NAV_HOME)
    broadcast_window.resize(1440, 900)
    broadcast_window.show()
    QTest.qWait(260)

    hero = broadcast_window.home_page.findChild(main_window_module.QWidget, "homeHero")
    greeting = broadcast_window.home_page.findChild(main_window_module.QLabel, "homeGreeting")
    image = hero.grab().toImage()
    inside = image.pixelColor(greeting.x() + 2, greeting.y() + 2)
    beside = image.pixelColor(max(2, greeting.x() - 8), greeting.y() + 2)
    distance = sum(abs(a - b) for a, b in zip(inside.getRgb()[:3], beside.getRgb()[:3]))
    assert distance < 25


def test_render_reference_screens(qapp, broadcast_window, tmp_path):
    output = Path(tmp_path)
    broadcast_window.resize(1440, 900)
    broadcast_window.show()

    captures = {
        "inicio.png": NAV_HOME,
        "television.png": NAV_TV,
        "radio.png": NAV_RADIO,
        "descargas.png": NAV_DOWNLOAD,
    }
    for filename, nav_id in captures.items():
        broadcast_window._on_nav_changed(nav_id)
        qapp.processEvents()
        QTest.qWait(260)  # deja terminar el fundido puntual de cambio de página
        target = output / filename
        assert broadcast_window.grab().save(str(target), "PNG")
        assert target.stat().st_size > 10_000

    settings = SettingsDialog(broadcast_window.settings, broadcast_window)
    settings.resize(720, 760)
    settings.show()
    qapp.processEvents()
    preferences = output / "preferencias.png"
    assert settings.grab().save(str(preferences), "PNG")
    assert preferences.stat().st_size > 10_000
    settings.close()

    print(f"VISUAL_QA_DIR={output}")

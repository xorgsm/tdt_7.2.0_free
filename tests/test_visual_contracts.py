"""Contratos estructurales del rediseño visual, ejecutados con Qt real."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from core import config as cfg
from ui import main_window as main_window_module
from ui import torrent_panel as torrent_panel_module
from ui.main_window import MainWindow, NAV_DOWNLOAD, NAV_RADIO, NAV_TV
from ui.carousel import Carousel, CarouselCard
from ui.widgets import EqualizerWidget, category_color
from ui import palette
from ui.command_palette import CommandPalette
from ui.dialogs import SettingsDialog
from ui.epg_dialog import EpgDialog
from ui.onboarding import OnboardingDialog
from ui.recurring_dialog import RecurringRecordingsDialog
from ui.stats_dialog import StatsDialog
from ui.toast import Toast


@pytest.fixture
def main_window(qapp, monkeypatch):
    """Construye la UI real aislando únicamente red, bandeja y hotkeys."""
    settings = cfg.DEFAULT_SETTINGS.copy()
    settings.update({"epg_url": "", "onboarding_shown": True})
    monkeypatch.setattr(main_window_module.cfg, "load_settings", lambda: settings.copy())
    monkeypatch.setattr(MainWindow, "_load_tv_channels", lambda self, force=False: None)
    monkeypatch.setattr(MainWindow, "_load_radio_stations", lambda self, force=False: None)
    monkeypatch.setattr(main_window_module.SystemMediaKeys, "start", lambda self: False)
    monkeypatch.setattr(main_window_module.TrayReminderController, "setup", lambda self: None)
    monkeypatch.setattr(torrent_panel_module, "paquete_disponible", lambda: False)

    window = MainWindow(activated=False)
    yield window
    window._is_closing = True
    window._media_keys.stop()
    window.deleteLater()
    qapp.processEvents()


def test_main_shell_keeps_splitter_and_public_qss_contracts(main_window):
    assert main_window.nav_rail.objectName() == "navRail"
    assert main_window.main_splitter.objectName() == "mainSplitter"
    assert main_window.main_splitter.orientation() == Qt.Horizontal
    assert main_window.player_frame.objectName() == "playerFrame"
    assert main_window.now_playing_bar.objectName() == "nowPlayingBar"


def test_main_actions_expose_semantic_visual_variants(main_window):
    assert main_window.play_btn.property("uiVariant") == "primary"
    assert main_window.record_btn.property("uiVariant") == "danger"
    assert main_window.cast_btn.property("uiVariant") == "cast"
    assert main_window.sleep_btn.property("uiVariant") == "sleep"


def test_home_uses_hero_and_shared_section_surfaces(main_window):
    hero = main_window.home_page.findChild(QWidget, "homeHero")
    assert hero is not None
    section_cards = [
        child
        for child in main_window.home_page.findChildren(QWidget, "dialogPanel")
        if child.property("uiSurface") == "homeSectionCard"
    ]
    assert len(section_cards) == 4


def test_navigation_changes_variant_without_local_title_stylesheet(main_window):
    main_window._on_nav_changed(NAV_TV)
    assert main_window.section_title.property("uiVariant") == "tv"
    assert main_window.section_title.styleSheet() == ""

    main_window._on_nav_changed(NAV_RADIO)
    assert main_window.section_title.property("uiVariant") == "radio"


def test_player_exposes_live_badge_hidden_until_playback(main_window):
    badge = main_window.findChild(QWidget, "liveBadge")
    assert badge is main_window.live_badge
    assert badge.isHidden()


def test_live_badge_follows_playback_state(main_window):
    main_window.set_live_badge_visible(True)
    assert not main_window.live_badge.isHidden()
    main_window.set_live_badge_visible(False)
    assert main_window.live_badge.isHidden()


def test_carousel_card_exposes_content_variant(qapp):
    tv_card = CarouselCard(
        {"type": "tv", "name": "Noticias", "url": "https://example.test/tv"},
        lambda _entry: None,
    )
    radio_card = CarouselCard(
        {"type": "radio", "name": "Radio", "url": "https://example.test/radio"},
        lambda _entry: None,
    )
    assert tv_card.objectName() == "carouselCard"
    assert tv_card.property("uiVariant") == "tv"
    assert radio_card.property("uiVariant") == "radio"
    assert tv_card.styleSheet() == ""
    tv_card.deleteLater()
    radio_card.deleteLater()


def test_empty_carousel_exposes_shared_empty_state(qapp):
    carousel = Carousel(lambda _entry: None, empty_text="Sin contenido")
    carousel.set_entries([])
    assert carousel.empty_label.property("uiState") == "empty"
    assert carousel.empty_label.styleSheet() == ""
    assert carousel.scroll.isHidden()
    carousel.deleteLater()


def test_library_uses_global_styles_and_named_lists(main_window):
    sidebar = main_window.library_sidebar
    assert sidebar.objectName() == "librarySidebar"
    assert sidebar.property("uiSurface") == "sidebar"
    assert sidebar.styleSheet() == ""
    assert sidebar.recent_list.objectName() == "libraryRecentList"
    assert sidebar.playlists_list.objectName() == "libraryPlaylistsList"


def test_empty_category_uses_shared_muted_color():
    color = category_color("")
    assert color.name() == palette.TEXT_DIM
    assert color.alpha() == 255


def test_equalizer_uses_global_broadcast_surface(qapp):
    equalizer = EqualizerWidget()
    assert equalizer.objectName() == "equalizerWidget"
    assert equalizer.styleSheet() == ""
    equalizer.stop()
    equalizer.deleteLater()


def test_download_panel_uses_shared_actions_progress_and_status(main_window):
    panel = main_window.download_panel
    assert panel.objectName() == "downloadPanel"
    assert panel.property("uiSurface") == "mediaPanel"
    assert panel.tabs.objectName() == "mediaTabs"
    assert panel.download_btn.property("uiVariant") == "primary"
    assert panel.cancel_btn.property("uiVariant") == "danger"
    assert panel.progress_bar.objectName() == "mediaProgress"
    assert panel.progress_bar.styleSheet() == ""

    panel._set_status("Falló", error=True)
    assert panel.status_label.property("uiState") == "error"
    assert panel.status_label.styleSheet() == ""


def test_torrent_panel_uses_semantic_toolbar_variants(main_window):
    panel = main_window.download_panel.torrent_panel
    assert panel.objectName() == "torrentPanel"
    assert panel.property("uiSurface") == "mediaPanel"
    assert panel.add_url_btn.property("uiVariant") == "primary"
    assert panel.remove_btn.property("uiVariant") == "danger"
    assert panel.info_btn.property("uiVariant") == "info"
    assert panel.add_url_btn.styleSheet() == ""


def test_podcast_panel_uses_shared_primary_and_danger_actions(main_window):
    panel = main_window.download_panel.podcast_panel
    assert panel.objectName() == "podcastPanel"
    assert panel.property("uiSurface") == "mediaPanel"
    assert panel.add_feed_btn.property("uiVariant") == "primary"
    assert panel.remove_feed_btn.property("uiVariant") == "danger"
    assert panel.status_label.objectName() == "mediaStatus"
    assert panel.status_label.styleSheet() == ""


def test_media_panels_do_not_embed_private_qss(main_window):
    panel = main_window.download_panel
    styled = [
        widget.objectName() or type(widget).__name__
        for widget in [panel, *panel.findChildren(QWidget)]
        if widget.styleSheet().strip()
    ]
    assert styled == []


def test_primary_dialogs_share_broadcast_surface(qapp, main_window):
    dialogs = [
        SettingsDialog(cfg.DEFAULT_SETTINGS.copy()),
        EpgDialog([], {}),
        OnboardingDialog(),
        StatsDialog(),
        RecurringRecordingsDialog(main_window, []),
    ]
    try:
        assert all(dialog.property("uiSurface") == "dialog" for dialog in dialogs)
    finally:
        for dialog in dialogs:
            dialog.deleteLater()


def _build_main_window(qapp, monkeypatch, **kwargs):
    """Mismo aislamiento que el fixture `main_window`, pero permitiendo
    elegir activated/es_version_free -- necesario para probar la versión
    free (activated=True, es_version_free=True), que el fixture no cubre
    porque siempre construye con activated=False."""
    settings = cfg.DEFAULT_SETTINGS.copy()
    settings.update({"epg_url": "", "onboarding_shown": True})
    monkeypatch.setattr(main_window_module.cfg, "load_settings", lambda: settings.copy())
    monkeypatch.setattr(MainWindow, "_load_tv_channels", lambda self, force=False: None)
    monkeypatch.setattr(MainWindow, "_load_radio_stations", lambda self, force=False: None)
    monkeypatch.setattr(main_window_module.SystemMediaKeys, "start", lambda self: False)
    monkeypatch.setattr(main_window_module.TrayReminderController, "setup", lambda self: None)
    monkeypatch.setattr(torrent_panel_module, "paquete_disponible", lambda: False)
    window = MainWindow(**kwargs)
    window._is_closing = True
    return window


def test_free_version_hides_downloads_and_cast(qapp, monkeypatch):
    """La versión free arranca con activated=True (para desbloquear TV/radio
    sin splash), pero eso no debe desbloquear Descargas ni Chromecast --
    ver comentario en MainWindow.__init__ y CLAUDE.md."""
    window = _build_main_window(qapp, monkeypatch, activated=True, es_version_free=True)
    try:
        # isHidden(), no isVisible(): la ventana nunca se muestra en el
        # test (sin show()), así que isVisible() sería False para
        # cualquier widget independientemente de lo que probamos --
        # mismo patrón que test_player_exposes_live_badge_hidden_until_playback.
        assert window.nav_group.button(NAV_DOWNLOAD).isHidden() is True
        assert window.cast_btn.isHidden() is True
    finally:
        window._media_keys.stop()
        window.deleteLater()
        qapp.processEvents()


def test_licensed_version_keeps_downloads_and_cast(qapp, monkeypatch):
    """Control: un cliente con licencia real activada (no free) sí conserva
    Descargas y Chromecast -- el fix de la versión free no debe restringir
    también este caso."""
    window = _build_main_window(qapp, monkeypatch, activated=True, es_version_free=False)
    try:
        assert window.nav_group.button(NAV_DOWNLOAD).isHidden() is False
        assert window.cast_btn.isHidden() is False
    finally:
        window._media_keys.stop()
        window.deleteLater()
        qapp.processEvents()


def test_floating_surfaces_use_global_theme(main_window):
    command = CommandPalette(main_window, [])
    toast = Toast(main_window, "Mensaje de prueba")
    assert command.property("uiSurface") == "floating"
    assert toast.property("uiSurface") == "floating"
    assert command.styleSheet() == ""
    assert toast.styleSheet() == ""
    command.deleteLater()
    toast.deleteLater()

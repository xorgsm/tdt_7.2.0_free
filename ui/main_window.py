"""
Ventana principal de TDT & Radio VIP — interfaz moderna.
Coder By X@R
"""
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, QUrl,
)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFrame,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMenuBar, QMessageBox,
    QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QSlider, QSplitter, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from ui import icons as app_icons
from core import config as cfg
from core.logger import log_file_path
from core import channels as tv_channels
from core import radio as radio_stations
from core import favorites as fav_store
from core import history as hist_store
from core import recorder as rec_module
from core import recording_schedule
from core import updater
from core.caster import CastSession, guess_stream_content_type
from core.dlna_caster import DLNASession
from player.vlc_player import VLCPlayer
from ui.cast_dialog import CastDeviceDialog, BACKEND_CHROMECAST
from ui.dialogs import SettingsDialog
from ui.equalizer_dialog import EqualizerDialog
from ui.style import ACCENT_PRESETS, build_style
from ui.visual import set_variant
from ui.download_panel import DownloadPanel
from ui import palette
from ui.channel_lists_controller import ChannelListsController
from ui.carousel import Carousel
from ui.command_palette import CommandPalette
from ui.epg_controller import EpgController
from ui.fetch_worker import (
    FetchWorker,
    process_events_during_shutdown,
    shutdown_workers,
)
from ui.library_controller import LibraryController
from ui.library_sidebar import LibrarySidebar
from ui.onboarding import OnboardingDialog
from ui.mosaic_view import MosaicView
from ui.recurring_dialog import RecurringRecordingsDialog
from ui.stats_dialog import StatsDialog
from ui.tray_controller import TrayReminderController
from ui.media_keys import (
    HOTKEY_NEXT, HOTKEY_PLAY_PAUSE, HOTKEY_PREV, HOTKEY_STOP, SystemMediaKeys,
)
from ui.playback_controller import PlaybackController
from ui.queue_controller import QueueController
from ui.window_chrome import WindowChrome
from ui.taskbar_controls import (
    BTN_NEXT, BTN_PLAY, BTN_PREV, BTN_STOP, BTN_MUTE, TaskbarControls, set_native_window_icon,
)
from ui.widgets import (
    ROLE_CUSTOM, ROLE_DATA, ROLE_FAV, ROLE_PLAYING,
    ChannelDelegate, ChannelGridDelegate, EqualizerWidget, LogoLoader,
)

NAV_HOME, NAV_TV, NAV_RADIO, NAV_FAV, NAV_HIST, NAV_DOWNLOAD = range(6)
# Títulos cortos a propósito: "Televisión (TDT)" y "Radio online" se
# comían casi todo el ancho disponible en la barra superior (título +
# botón Guía + filtro de categoría + buscador en una sola fila), dejando
# el propio título cortado en ventanas no muy anchas. La aclaración "TDT"
# y "online" ya la da el icono/tooltip del riel, no hace falta repetirla aquí.
SECTION_TITLES = {
    NAV_HOME: "Inicio",
    NAV_TV: "Televisión",
    NAV_RADIO: "Radio",
    NAV_FAV: "Favoritos",
    NAV_HIST: "Historial",
    NAV_DOWNLOAD: "Descargas",
}
# Mismo color por sección que ya usan los iconos del riel lateral, para
# poder pintar con él también el título de la barra superior (más
# acentos de color coherentes con lo que ya existía, no colores nuevos
# sueltos). Se define aquí, a nivel de módulo, para que tanto
# _build_nav_rail() como _on_nav_changed() lean del mismo sitio.
SECTION_COLORS = {
    NAV_HOME: ACCENT_PRESETS["Verde"],
    NAV_TV: palette.ACCENT_INFO,
    NAV_RADIO: palette.ACCENT_CATEGORY_ORANGE,
    NAV_FAV: palette.ACCENT,
    NAV_HIST: ACCENT_PRESETS["Violeta"],
    NAV_DOWNLOAD: palette.ACCENT_CAST,
}
SECTION_VARIANTS = {
    NAV_HOME: "success",
    NAV_TV: "tv",
    NAV_RADIO: "radio",
    NAV_FAV: "primary",
    NAV_HIST: "sleep",
    NAV_DOWNLOAD: "cast",
}
DEFAULT_DOWNLOADS_DIRNAME = "TDT Radio VIP"


class MainWindow(QMainWindow):
    def __init__(self, activated: bool = False, es_version_free: bool = False):
        super().__init__()
        self._is_closing = False
        self.activated = activated
        # Distingue "activado de verdad con un código" de "versión Free,
        # desbloqueada por defecto" — main_free.py pasa activated=True para
        # abrir la reproducción de TV/radio sin pedir código, pero eso no es
        # lo mismo que un cliente que sí ha activado con su código real.
        # Descargas y Chromecast (ver más abajo: NAV_DOWNLOAD, cast_btn, y
        # la entrada "Ir a Descargas" de la paleta de comandos) exigen
        # además "not es_version_free" -- si no, activated=True en
        # main_free.py las desbloquearía igual que en un cliente con
        # licencia real, contradiciendo lo que anuncia el propio diálogo
        # "Acerca de" ("sin Descargas ni Chromecast").
        self.es_version_free = es_version_free
        self.setObjectName("mainWindowRoot")
        self.setWindowTitle(f"TDT & Radio VIP {cfg.APP_VERSION} — Coder By X@R")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # El LibrarySidebar (Recientes/Playlists) arranca OCULTO a propósito
        # (ver _build_nav_rail/_toggle_library_sidebar): con él visible por
        # defecto la ventana necesitaba 210px de más, y en pantallas más
        # pequeñas la app se abría demasiado grande y con la barra de
        # controles y la barra superior apretadas. Quien lo quiera, lo
        # activa con el botón de biblioteca del riel — sigue disponible,
        # solo que no ocupa sitio si no se pide.
        self.resize(1180, 640)
        # 1000px de mínimo era más de lo que la propia interfaz necesita
        # (riel 76 + lista de canales 420 + panel de vídeo 300 + divisor
        # ≈ 800-820px reales): al ser mayor que la mitad del ancho de
        # muchas pantallas (p. ej. 1920px ÷ 2 = 960), Windows no dejaba
        # encajar la ventana en la mitad de la pantalla ni al arrastrarla
        # al borde izquierdo -- se quedaba "a medias" (bug reportado).
        # 900 sigue teniendo margen sobre el mínimo real de la interfaz.
        self.setMinimumSize(900, 580)

        self.settings = cfg.load_settings()
        self.favorites = fav_store.load_favorites()
        self.history = hist_store.load_history()
        self.epg_guide = {}
        self.logo_loader = LogoLoader()

        self.tv_channels_data = []
        self.radio_stations_data = []

        self.current_type: Optional[str] = None
        self.current_name: Optional[str] = None
        self.current_url: Optional[str] = None
        self.current_logo: str = ""
        self.current_tvg_id: str = ""
        self._playback_failed = False
        self._playback_token = 0
        self._active_list = None
        self._active_row = -1
        self._auto_skip_count = 0
        self._fade_anim = None

        self.downloads_dir = self.settings.get("downloads_dir") or str(
            Path.home() / "Downloads" / DEFAULT_DOWNLOADS_DIRNAME
        )
        self.recorder = rec_module.Recorder(self.downloads_dir)
        # Grabación programada actualmente en curso (ScheduledRecording),
        # o None si self.recorder está libre o grabando algo manual. Sirve
        # para que _check_scheduled_recordings() sepa cuál cerrar cuando
        # llegue su hora de fin, y para que toggle_recording() (parada
        # manual, ver PlaybackController) también limpie la programación
        # si el usuario para a mano una grabación que en realidad venía de
        # la EPG.
        self._scheduled_recording_active: Optional[recording_schedule.ScheduledRecording] = None
        self._cast_session = CastSession()
        self._dlna_session = DLNASession()
        self._player_fullscreen = False
        self._was_maximized_before_fs = False
        self._pseudo_maximizado = False
        self._geometria_normal = None
        self._pip_mode = False
        self._geometria_antes_pip = None
        # Preferencia persistente (no de "esta reproducción"): se aplica
        # cada vez que se sintoniza un canal de TV -- ver
        # PlaybackController.play()/_apply_audio_only_state().
        self._audio_only_tv = self.settings.get("audio_only_tv", False)
        self._taskbar = TaskbarControls()
        self._native_icon_applied = False

        # Creado ANTES de _build_ui(): la construcción de la interfaz conecta
        # varias señales (botones de reproducción, temporizador de apagado...)
        # directamente a métodos de este controlador.
        self.playback = PlaybackController(self)
        self.window_chrome = WindowChrome(self)
        self.lists = ChannelListsController(self)
        self.queue = QueueController(self)
        self.epg = EpgController(self)
        self.library = LibraryController(self)
        self.tray = TrayReminderController(self)

        self._build_ui()
        self._registrar_atajos()

        # Teclas multimedia del teclado (play/pausa, siguiente, anterior,
        # detener) funcionando en segundo plano, no solo con la ventana en
        # foco. Se registran aquí porque no dependen del HWND (a diferencia
        # del icono nativo / botones de la barra de tareas en showEvent):
        # RegisterHotKey con hWnd=None no necesita que la ventana ya esté
        # creada a nivel de Win32.
        self._media_keys = SystemMediaKeys()
        self._media_keys.bind(HOTKEY_PLAY_PAUSE, self.playback.toggle_play)
        self._media_keys.bind(HOTKEY_STOP, self.playback.stop_playback)
        self._media_keys.bind(HOTKEY_NEXT, self.playback.play_next)
        self._media_keys.bind(HOTKEY_PREV, self.playback.play_prev)
        self._media_keys.start()

        self._load_tv_channels()
        self._load_radio_stations()
        self.lists.refresh_favorites_tab()
        self.lists.refresh_history_tab()
        if self.settings.get("epg_url"):
            self.epg.load()

        self.tray.setup()

        if not self.player.disponible:
            # Antes esto reventaba en el arranque con un error críptico. Ahora
            # la app abre igual (descargas, listas, favoritos siguen usables)
            # y se explica qué falta.
            QTimer.singleShot(300, self._avisar_vlc_no_disponible)

        if not self.settings.get("onboarding_shown"):
            # Con un pequeño retraso, para que se vea primero la ventana
            # principal ya construida detrás en vez de un diálogo modal
            # tapándolo todo desde el primer frame.
            QTimer.singleShot(500, self._mostrar_bienvenida)

    def _mostrar_bienvenida(self):
        OnboardingDialog(self).exec()
        self.settings["onboarding_shown"] = True
        if not cfg.save_settings(self.settings):
            QMessageBox.warning(
                self,
                "No se pudieron guardar los ajustes",
                "No se pudieron guardar los ajustes. Inténtalo de nuevo.",
            )

    # _setup_tray_and_reminders / _check_epg_reminders / _check_scheduled_recordings /
    # _check_scheduled_recording_alive / _on_tray_message_clicked viven ahora en
    # ui.tray_controller.TrayReminderController (self.tray).

    def _avisar_vlc_no_disponible(self):
        QMessageBox.warning(
            self,
            "Motor de vídeo no disponible",
            f"{self.player.motivo_no_disponible()}\n\n"
            "La reproducción de TV y radio no funcionará. El resto de la "
            "aplicación (descargas, listas y favoritos) sigue disponible.",
        )
        self.statusBar().showMessage("VLC no disponible: la reproducción está desactivada.")

    # ---------- Construcción de la interfaz ----------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appSurface")
        raiz_v = QVBoxLayout(central)
        raiz_v.setContentsMargins(0, 0, 0, 0)
        raiz_v.setSpacing(0)

        self.title_bar = self._build_title_bar()
        raiz_v.addWidget(self.title_bar)

        cuerpo = QWidget()
        root = QHBoxLayout(cuerpo)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav_rail = self._build_nav_rail()
        root.addWidget(self.nav_rail)

        # Sidebar de biblioteca (Recientes + Playlists = carpetas de
        # favoritos), estilo Spotify: panel aditivo entre el riel de
        # iconos y el contenido principal, colapsable con el botón de
        # abajo del todo en el riel. No sustituye a las pestañas de
        # Favoritos/Historial -- es un atajo hacia ellas.
        self.library_sidebar = LibrarySidebar(self, self._open_favorites_folder)
        self.library_sidebar.setVisible(False)
        root.addWidget(self.library_sidebar)
        # Fondo vacío del sidebar (y el hueco bajo las entradas de
        # Recientes/Playlists) también arrastra la ventana, igual que la
        # barra de título -- ver WindowChrome.event_filter(). Con este
        # panel abierto ocupa buena parte de la altura de la ventana, y
        # antes la única zona de arrastre era la franja fina de arriba.
        self.library_sidebar.installEventFilter(self)
        self.library_sidebar.recent_list.viewport().installEventFilter(self)
        self.library_sidebar.playlists_list.viewport().installEventFilter(self)

        content = QVBoxLayout()
        content.setContentsMargins(20, 18, 12, 16)
        content.setSpacing(12)
        content.addLayout(self._build_top_bar())
        content.addWidget(self._build_content_stack(), stretch=1)

        # setChecked(True) sobre el botón de Inicio (más arriba, en
        # _build_nav_rail) no dispara idClicked por sí solo — solo lo hace
        # un clic real del usuario. Sin esto, la portada se abriría vacía
        # hasta que el usuario cambiara de sección y volviera a Inicio.
        self._on_nav_changed(NAV_HOME)

        self.content_widget = QWidget()
        self.content_widget.setLayout(content)
        # Mínimo real: por debajo de esto, el título + filtro de categoría +
        # buscador de la barra superior no caben y se cortan (era el bug del
        # buscador cortado). El splitter no puede arrastrarse más allá.
        self.content_widget.setMinimumWidth(420)

        player_panel = self._build_player_panel()
        # La fila de controles ya no crece con el número de funciones: las
        # cinco acciones secundarias (pistas, pantalla completa, PiP,
        # temporizador, cola) que antes tenían un botón circular propio y
        # obligaban a un mínimo de 430px ahora viven en un único botón
        # "Más opciones" (ver _build_now_playing_bar). 300px sigue dejando
        # margen de sobra para el resto de la fila (favoritos, cast,
        # detener, play, grabar, silenciar, más) sin que se solape nada, y
        # permite que la ventana encaje en la mitad de pantallas normales
        # en vez del mínimo inflado de antes.
        player_panel.setMinimumWidth(300)

        # Antes el reparto entre la lista y el vídeo era un stretch fijo
        # (3:2) dentro del QHBoxLayout: no había forma de ajustarlo a mano.
        # Con un splitter, el usuario arrastra la línea divisoria él mismo,
        # y los anchos mínimos de arriba evitan que se coma ninguno de los
        # dos lados por accidente.
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.content_widget)
        self.main_splitter.addWidget(player_panel)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([580, 430])
        root.addWidget(self.main_splitter, stretch=1)
        raiz_v.addWidget(cuerpo, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().addPermanentWidget(QSizeGrip(self))
        self.statusBar().showMessage("Listo.")
        self.player.set_volume(self.volume_slider.value())

    def _build_nav_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("navRail")
        rail.setFixedWidth(76)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 18, 0, 12)
        layout.setSpacing(4)

        brand = QLabel("X@R")
        brand.setObjectName("brandLabel")
        brand.setAlignment(Qt.AlignCenter)
        layout.addWidget(brand)

        version_label = QLabel(cfg.APP_VERSION)
        version_label.setObjectName("versionLabel")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)
        layout.addSpacing(6)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        # Cada icono con su propio color (a juego con la paleta ya usada en
        # categorías/ecualizador), en vez de un gris único para los tres.
        # En estado activo se cambia siempre a un tono oscuro, porque el
        # fondo del botón activo es dorado y un icono claro perdería
        # contraste — el color de marca lo pone el fondo, no el icono.
        nav_icon_builders = {
            NAV_HOME: (app_icons.icon_home, SECTION_COLORS[NAV_HOME]),
            NAV_TV: (app_icons.icon_tv, SECTION_COLORS[NAV_TV]),
            NAV_RADIO: (app_icons.icon_radio, SECTION_COLORS[NAV_RADIO]),
            NAV_HIST: (app_icons.icon_history, SECTION_COLORS[NAV_HIST]),
        }
        nav_defs = [
            (NAV_HOME, "Inicio"),
            (NAV_TV, "Televisión"),
            (NAV_RADIO, "Radio"),
            (NAV_FAV, "Favoritos"),
            (NAV_HIST, "Historial"),
            (NAV_DOWNLOAD, "Descargas"),
        ]
        nav_glyphs = {NAV_FAV: "\u2605", NAV_DOWNLOAD: "\u2B07"}
        for nav_id, tooltip in nav_defs:
            btn = QToolButton()
            btn.setObjectName("navButton")
            set_variant(btn, SECTION_VARIANTS[nav_id])
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            if nav_id in nav_glyphs:
                btn.setText(nav_glyphs[nav_id])
            else:
                builder, inactive_color = nav_icon_builders[nav_id]
                btn.setIconSize(QSize(30, 30))
                # size=32 explícito: los icon_*() por defecto dibujan a
                # 26px, y mostrarlos a 30px sin pedir un pixmap más grande
                # los habría escalado hacia arriba (borroso). Con 32px de
                # origen, Qt reduce ligeramente en vez de ampliar.
                btn.setIcon(builder(inactive_color, size=32))
                btn.toggled.connect(
                    lambda checked, b=btn, f=builder, c=inactive_color: b.setIcon(
                        f(palette.BG_ROOT if checked else c, size=32)
                    )
                )
            self.nav_group.addButton(btn, nav_id)
            layout.addWidget(btn)
            # El botón de descargas solo aparece con licencia activada de
            # verdad -- nunca en la versión free, aunque esta arranque con
            # activated=True para desbloquear TV/radio (ver comentario en
            # __init__).
            if nav_id == NAV_DOWNLOAD and (not self.activated or self.es_version_free):
                btn.setVisible(False)

        self.nav_group.button(NAV_HOME).setChecked(True)
        self.nav_group.idClicked.connect(self._on_nav_changed)

        layout.addStretch(1)

        self.library_toggle_btn = QToolButton()
        self.library_toggle_btn.setObjectName("navButton")
        self.library_toggle_btn.setToolTip("Mostrar/ocultar biblioteca")
        self.library_toggle_btn.setCheckable(True)
        self.library_toggle_btn.setChecked(False)
        self.library_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.library_toggle_btn.setIconSize(QSize(26, 26))
        self.library_toggle_btn.setIcon(app_icons.icon_library(palette.TEXT_MUTED))
        self.library_toggle_btn.toggled.connect(self._toggle_library_sidebar)
        layout.addWidget(self.library_toggle_btn)

        return rail

    def _toggle_library_sidebar(self, visible: bool):
        self.library_sidebar.setVisible(visible)
        self.library_toggle_btn.setIcon(
            app_icons.icon_library(palette.ACCENT if visible else palette.TEXT_MUTED)
        )

    def _open_favorites_folder(self, folder):
        """
        Salta a la pestaña de Favoritos y, si se indica una carpeta, la deja
        seleccionada en el filtro -- llamado desde el panel de biblioteca al
        pinchar una "playlist". folder=None significa "todos los favoritos,
        sin filtrar por carpeta".
        """
        self.nav_group.button(NAV_FAV).click()
        if folder:
            idx = self.group_filter.findText(folder)
            if idx >= 0:
                self.group_filter.setCurrentIndex(idx)
        else:
            self.group_filter.setCurrentIndex(0)

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(12)

        self.section_title = QLabel(SECTION_TITLES[NAV_HOME])
        self.section_title.setObjectName("sectionTitle")
        # Sin mínimo protegido, un QHBoxLayout bajo presión de espacio lo
        # encoge a él antes que a group_filter/search_box (que sí tienen
        # min/max explícitos) -- por eso "Televisión" salía cortado en
        # ventanas estrechas. 110px cubre el título más largo ("Televisión")
        # con el tamaño de fuente actual; si aun así falta sitio, se elide
        # con "…" en vez de recortarse sin avisar.
        self.section_title.setMinimumWidth(110)
        self.section_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        bar.addWidget(self.section_title)
        bar.addStretch(1)

        self.epg_btn = QPushButton("Guía")
        self.epg_btn.setToolTip("Ver parrilla de programación")
        self.epg_btn.clicked.connect(self.epg.open_dialog)
        bar.addWidget(self.epg_btn)

        # Alternar lista/cuadrícula, solo tiene sentido en Televisión --
        # visibilidad controlada junto al resto en _on_nav_changed().
        self.tv_view_toggle = QToolButton()
        self.tv_view_toggle.setObjectName("navButton")
        self.tv_view_toggle.setCheckable(True)
        self.tv_view_toggle.setCursor(Qt.PointingHandCursor)
        self.tv_view_toggle.setIconSize(QSize(18, 18))
        # Iconos dibujados a mano (ver ui/icons.py), no texto: el carácter
        # "⊞" que se usaba antes con setText() no está garantizado en Segoe
        # UI y salía en blanco -- solo se veía el fondo dorado/de acento del
        # estado :checked, sin ningún icono encima (reportado con captura).
        self.tv_view_toggle.setIcon(app_icons.icon_grid_view(palette.TEXT_DIM))
        self.tv_view_toggle.setToolTip("Ver en cuadrícula")
        self.tv_view_toggle.setFixedSize(30, 30)
        self.tv_view_toggle.toggled.connect(self._toggle_tv_grid_view)
        bar.addWidget(self.tv_view_toggle)

        self.group_filter = QComboBox()
        self.group_filter.setObjectName("groupFilter")
        self.group_filter.addItem("Todas las categorías")
        self.group_filter.currentTextChanged.connect(self.lists.filter_current_list)
        # Antes con setFixedWidth(200): a la anchura mínima de ventana que
        # permite la app (900px), el título + 200 + 240 del buscador no
        # cabían en la columna de contenido, y al ser anchos fijos Qt no
        # podía encogerlos — se salían del panel sin más, cortando la
        # esquina redondeada del buscador. Con mínimo/máximo, encogen antes
        # de desbordar.
        self.group_filter.setMinimumWidth(130)
        self.group_filter.setMaximumWidth(200)
        bar.addWidget(self.group_filter)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Buscar canal o emisora…")
        self.search_box.setMinimumWidth(140)
        self.search_box.setMaximumWidth(240)
        self.search_box.textChanged.connect(self.lists.filter_current_list)
        bar.addWidget(self.search_box)

        return bar

    def _toggle_tv_grid_view(self, checked: bool):
        """
        Alterna la lista de TV entre filas (ChannelDelegate, la vista de
        toda la vida) y cuadrícula de tarjetas (ChannelGridDelegate, estilo
        catálogo). Solo afecta a tv_list -- radio, favoritos e historial
        siguen en modo lista siempre.
        """
        if checked:
            self.tv_list.setItemDelegate(self.grid_delegate)
            self.tv_list.setViewMode(QListWidget.IconMode)
            self.tv_list.setFlow(QListWidget.LeftToRight)
            self.tv_list.setResizeMode(QListWidget.Adjust)
            self.tv_list.setMovement(QListWidget.Static)
            self.tv_list.setSpacing(4)
            self.tv_list.setGridSize(QSize(ChannelGridDelegate.CARD_SIZE, ChannelGridDelegate.CARD_SIZE))
            # BG_ROOT (oscuro) cuando está marcado, porque :checked pone de
            # fondo el color de acento claro -- mismo criterio que ya usan
            # los botones del riel de navegación (ver nav_icon_builders).
            self.tv_view_toggle.setIcon(app_icons.icon_list_view(palette.BG_ROOT))
            self.tv_view_toggle.setToolTip("Ver en lista")
        else:
            self.tv_list.setItemDelegate(self.delegate)
            self.tv_list.setViewMode(QListWidget.ListMode)
            self.tv_list.setFlow(QListWidget.TopToBottom)
            self.tv_list.setGridSize(QSize())
            self.tv_view_toggle.setIcon(app_icons.icon_grid_view(palette.TEXT_DIM))
            self.tv_view_toggle.setToolTip("Ver en cuadrícula")
        self.tv_list.viewport().update()

    def _build_content_stack(self) -> QStackedWidget:
        self.stack = QStackedWidget()
        self.delegate = ChannelDelegate()
        self.grid_delegate = ChannelGridDelegate()

        self.tv_list = self._make_list()
        self.radio_list = self._make_list()
        self.fav_list = self._make_list(reorderable=True)
        self.hist_list = self._make_list()
        self.download_panel = DownloadPanel(
            dest_dir=self.downloads_dir,
            on_dest_changed=self._on_downloads_dir_changed,
            on_cast=self._cast_local_file,
            on_finished=self._on_download_finished,
            on_play_audio=self._play_podcast_episode,
        )
        self.home_page = self._build_home_page()

        for page in (self.home_page, self.tv_list, self.radio_list, self.fav_list,
                     self.hist_list, self.download_panel):
            self.stack.addWidget(page)

        return self.stack

    def _build_home_page(self) -> QWidget:
        """
        Portada de bienvenida: accesos rápidos a TV/Radio, y un vistazo a lo
        último visto y a los favoritos, sin tener que entrar en cada sección.
        Reutiliza _make_list() (misma tarjeta, mismo clic-para-reproducir,
        mismo menú contextual que el resto de la app) en vez de inventar un
        sistema de tarjetas nuevo sin poder probarlo antes de dártelo.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("homeScroll")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 20, 12)
        layout.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("homeHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(10)

        greeting = QLabel("Bienvenido de nuevo")
        greeting.setObjectName("homeGreeting")
        hero_layout.addWidget(greeting)

        subtitle = QLabel("Elige algo para ver o escuchar, o retoma donde lo dejaste.")
        subtitle.setObjectName("dialogSubtitle")
        hero_layout.addWidget(subtitle)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)

        tv_btn = QPushButton(" Ver TV en directo")
        tv_btn.setObjectName("homeQuickButton")
        set_variant(tv_btn, "tv")
        # Icono oscuro a juego con el "color" que ya usa
        # QPushButton#homeQuickButton[uiVariant="tv"] en ui/style.py para el
        # texto sobre el fondo palette.ACCENT_INFO -- un literal aparte aquí
        # se habría podido desincronizar si ese tono cambia más adelante.
        tv_btn.setIcon(app_icons.icon_tv(palette.BG_ROOT))
        tv_btn.setIconSize(QSize(20, 20))
        tv_btn.setCursor(Qt.PointingHandCursor)
        tv_btn.clicked.connect(lambda: self.nav_group.button(NAV_TV).click())
        quick_row.addWidget(tv_btn)

        radio_btn = QPushButton(" Escuchar Radio")
        radio_btn.setObjectName("homeQuickButtonAlt")
        set_variant(radio_btn, "radio")
        radio_btn.setIcon(app_icons.icon_radio(palette.TEXT_PRIMARY))
        radio_btn.setIconSize(QSize(20, 20))
        radio_btn.setCursor(Qt.PointingHandCursor)
        radio_btn.clicked.connect(lambda: self.nav_group.button(NAV_RADIO).click())
        quick_row.addWidget(radio_btn)
        quick_row.addStretch(1)
        hero_layout.addLayout(quick_row)
        layout.addWidget(hero)

        # ---- Ahora en antena (qué está echando cada canal, vía EPG) ----
        panel_antena = QFrame()
        panel_antena.setObjectName("dialogPanel")
        panel_antena.setProperty("uiSurface", "homeSectionCard")
        pa_layout = QVBoxLayout(panel_antena)
        pa_layout.setContentsMargins(16, 14, 16, 14)
        pa_layout.setSpacing(8)
        lbl_antena = QLabel("AHORA EN ANTENA")
        lbl_antena.setObjectName("dialogSectionLabel")
        pa_layout.addWidget(lbl_antena)
        self.home_on_air_carousel = Carousel(
            on_activate=self._activate_home_entry,
            logo_loader=self.logo_loader,
            empty_text="Configura una guía de programación (EPG) en Configuración para ver esto.",
        )
        pa_layout.addWidget(self.home_on_air_carousel)
        layout.addWidget(panel_antena)
        self.panel_antena = panel_antena

        # ---- Recientes (carrusel horizontal, estilo Spotify) ----
        panel_recientes = QFrame()
        panel_recientes.setObjectName("dialogPanel")
        panel_recientes.setProperty("uiSurface", "homeSectionCard")
        pr_layout = QVBoxLayout(panel_recientes)
        pr_layout.setContentsMargins(16, 14, 16, 14)
        pr_layout.setSpacing(8)
        lbl_recientes = QLabel("RECIENTES")
        lbl_recientes.setObjectName("dialogSectionLabel")
        pr_layout.addWidget(lbl_recientes)
        self.home_recent_carousel = Carousel(
            on_activate=self._activate_home_entry,
            logo_loader=self.logo_loader,
            empty_text="Todavía no has visto ni escuchado nada.",
        )
        pr_layout.addWidget(self.home_recent_carousel)
        layout.addWidget(panel_recientes)

        # ---- Recomendado para ti (carrusel horizontal) ----
        panel_recomendado = QFrame()
        panel_recomendado.setObjectName("dialogPanel")
        panel_recomendado.setProperty("uiSurface", "homeSectionCard")
        pv_layout = QVBoxLayout(panel_recomendado)
        pv_layout.setContentsMargins(16, 14, 16, 14)
        pv_layout.setSpacing(8)
        lbl_recomendado = QLabel("RECOMENDADO PARA TI")
        lbl_recomendado.setObjectName("dialogSectionLabel")
        pv_layout.addWidget(lbl_recomendado)
        self.home_recommended_carousel = Carousel(
            on_activate=self._activate_home_entry,
            logo_loader=self.logo_loader,
            empty_text="Actualiza los canales de TV para ver sugerencias aquí.",
        )
        pv_layout.addWidget(self.home_recommended_carousel)

        # ---- Favoritos ----
        panel_favs = QFrame()
        panel_favs.setObjectName("dialogPanel")
        panel_favs.setProperty("uiSurface", "homeSectionCard")
        pf_layout = QVBoxLayout(panel_favs)
        pf_layout.setContentsMargins(16, 14, 16, 14)
        pf_layout.setSpacing(8)
        lbl_favs = QLabel("TUS FAVORITOS")
        lbl_favs.setObjectName("dialogSectionLabel")
        pf_layout.addWidget(lbl_favs)
        self.home_fav_list = self._make_list()
        self.home_fav_list.setFixedHeight(5 * ChannelDelegate.ROW_HEIGHT + 12)
        self.home_fav_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pf_layout.addWidget(self.home_fav_list)
        self.home_fav_empty = QLabel("Todavía no tienes ningún favorito marcado.")
        self.home_fav_empty.setStyleSheet(f"color: {palette.TEXT_DIM}; font-size: 8pt;")
        pf_layout.addWidget(self.home_fav_empty)

        # "Recomendado para ti" y "Tus favoritos" van uno junto al otro
        # (2:1, como en la referencia de Stitch) en vez de apilados a lo
        # largo de toda la portada -- ambos son paneles cortos y quedaba
        # mucho hueco vacío a los lados si ocupaban el ancho completo.
        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(16)
        secondary_row.addWidget(panel_recomendado, 2)
        secondary_row.addWidget(panel_favs, 1)
        layout.addLayout(secondary_row)

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _refresh_home_page(self):
        """Puebla los carruseles de 'Recientes' y 'Recomendado para ti', y la
        lista de favoritos destacados, con los mismos datos que ya usan sus
        propias pestañas — se llama cada vez que se entra en Inicio, para
        que nunca se quede desactualizada respecto a lo que se ha
        visto/marcado mientras tanto."""
        custom_tv = {c.name for c in tv_channels.load_custom_channels()}
        custom_radio = {s.name for s in radio_stations.load_custom_stations()}

        self.home_on_air_carousel.set_entries(self.epg.now_on_air_entries())
        self.home_recent_carousel.set_entries(self.history[:12])
        self.home_recommended_carousel.set_entries(self._compute_recommendations())

        self.home_fav_list.clear()
        destacados = self.favorites[:5]
        for fav in destacados:
            item = QListWidgetItem()
            data = dict(fav)
            data["group"] = fav.get("folder", "")
            item.setData(ROLE_DATA, data)
            item.setData(ROLE_FAV, True)
            item.setData(ROLE_PLAYING, self.current_type == fav["type"] and self.current_name == fav["name"])
            is_custom = fav["name"] in (custom_tv if fav["type"] == "tv" else custom_radio)
            item.setData(ROLE_CUSTOM, is_custom)
            self.home_fav_list.addItem(item)
            self.lists.request_logo(fav.get("logo", ""), item, self.home_fav_list)
        self.home_fav_list.setVisible(bool(destacados))
        self.home_fav_empty.setVisible(not destacados)

    def _activate_home_entry(self, entry: dict):
        """Reproduce una tarjeta de los carruseles de Inicio (Recientes o
        Recomendado para ti). Solo llama a play(): no depende de una fila
        de QListWidget como activate_item(), porque las tarjetas del
        carrusel no viven dentro de ninguna lista navegable."""
        self.playback.play(
            entry.get("type", "tv"), entry.get("name", ""), entry.get("url", ""),
            entry.get("tvg_id", ""), entry.get("logo", ""),
        )

    def _compute_recommendations(self, limit: int = 12) -> list:
        """
        Heurística de "Recomendado para ti" sin necesidad de trackear nada
        nuevo: el historial solo guarda una entrada por canal (la más
        reciente, ver core/history.add_entry), así que no hay forma de
        contar reproducciones -- en su lugar, se recomienda por categoría:
        canales de TV de las mismas categorías que ya has visto o
        marcado como favorito, que todavía no hayas visto ni marcado. Si
        no hay categorías en común todavía (usuario nuevo, o categorías no
        cargadas), se completa con canales de TV que aún no aparezcan ni
        en historial ni en favoritos, para que la sección no salga vacía
        salvo que de verdad no haya canales cargados.
        """
        vistos_o_favoritos = {(e.get("type"), e.get("name")) for e in self.history}
        vistos_o_favoritos |= {(f.get("type"), f.get("name")) for f in self.favorites}

        categorias_interes = {
            ch.group for ch in self.tv_channels_data
            if ch.group and ("tv", ch.name) in vistos_o_favoritos
        }

        recomendaciones = []
        nombres_añadidos = set()

        if categorias_interes:
            for ch in self.tv_channels_data:
                if ("tv", ch.name) in vistos_o_favoritos or ch.name in nombres_añadidos:
                    continue
                if ch.group in categorias_interes:
                    recomendaciones.append({
                        "type": "tv", "name": ch.name, "url": ch.url,
                        "logo": ch.logo, "tvg_id": ch.tvg_id,
                    })
                    nombres_añadidos.add(ch.name)
                if len(recomendaciones) >= limit:
                    break

        if len(recomendaciones) < limit:
            for ch in self.tv_channels_data:
                if ("tv", ch.name) in vistos_o_favoritos or ch.name in nombres_añadidos:
                    continue
                recomendaciones.append({
                    "type": "tv", "name": ch.name, "url": ch.url,
                    "logo": ch.logo, "tvg_id": ch.tvg_id,
                })
                nombres_añadidos.add(ch.name)
                if len(recomendaciones) >= limit:
                    break

        return recomendaciones

    def _on_downloads_dir_changed(self, new_dir: str):
        self.downloads_dir = new_dir
        self.settings["downloads_dir"] = new_dir
        if not cfg.save_settings(self.settings):
            QMessageBox.warning(
                self,
                "No se pudieron guardar los ajustes",
                "No se pudieron guardar los ajustes. Inténtalo de nuevo.",
            )

    def _on_download_finished(self, nombre: str, _ruta: str):
        """
        Aviso de bandeja al terminar una descarga -- útil sobre todo si la
        ventana estaba minimizada mientras se descargaba algo largo, para
        no tener que ir comprobando la pestaña de Descargas a mano.
        """
        self.tray.notify("Descarga completada", nombre)

    # ---------- Ecualizador ----------

    def _apply_saved_equalizer(self):
        """
        Aplica el ecualizador guardado (ver ui/equalizer_dialog.py) nada
        más crear el reproductor, para que ya esté activo desde el primer
        canal/emisora de la sesión y no solo después de abrir el diálogo.
        Si el nº de bandas guardado no coincide con el que da esta libVLC
        (p. ej. tras cambiar de máquina o de versión de VLC), se ignora en
        vez de aplicar una configuración a medias.
        """
        if not self.settings.get("equalizer_enabled", False):
            return
        bandas = self.settings.get("equalizer_bands") or []
        if len(bandas) != self.player.equalizer_band_count():
            return
        self.player.set_equalizer(self.settings.get("equalizer_preamp", 0.0), bandas)

    def _open_equalizer_dialog(self):
        EqualizerDialog(self).exec()

    # ---------- Enviar a la TV (Chromecast / Google Cast / DLNA) ----------

    def _active_cast_session(self):
        """Sesión de casting con un dispositivo conectado ahora mismo, o None."""
        if self._cast_session.device is not None:
            return self._cast_session
        if self._dlna_session.device is not None:
            return self._dlna_session
        return None

    def _on_cast_live_clicked(self):
        sesion = self._active_cast_session()
        if sesion is not None:
            sesion.disconnect()
            self.cast_btn.setChecked(False)
            self.statusBar().showMessage("Envío a la TV detenido.", 4000)
            return

        if not self.current_url:
            self.cast_btn.setChecked(False)
            QMessageBox.information(
                self, "Nada en reproducción", "Elige un canal o una emisora primero."
            )
            return

        content_type = guess_stream_content_type(self.current_url, self.current_type or "")
        self._open_cast_picker_and_send(
            title=self.current_name or "", url=self.current_url, content_type=content_type
        )

    def _play_podcast_episode(self, url: str, title: str):
        """
        Reproduce un episodio de podcast (pestaña Descargas > Podcasts) con
        el mismo reproductor de audio que la radio -- un episodio de
        podcast no es más que una URL de audio, así que se reutiliza
        PlaybackController.play() en vez de montar un reproductor aparte.
        """
        self.playback.play("radio", title, url)

    def _cast_local_file(self, filepath: str, title: str):
        if not os.path.isfile(filepath):
            QMessageBox.warning(
                self, "Archivo no encontrado", "El archivo descargado ya no está en esa ubicación."
            )
            return
        self._open_cast_picker_and_send(title=title, local_path=filepath)

    def _open_cast_picker_and_send(
        self, *, title: str, url: str | None = None, local_path: str | None = None,
        content_type: str | None = None,
    ):
        sesion_activa = self._active_cast_session()
        if sesion_activa is not None:
            sesion_activa.disconnect()

        dialog = CastDeviceDialog(self)
        try:
            if dialog.exec() != QDialog.Accepted or not dialog.selected_name:
                self.cast_btn.setChecked(False)
                return

            backend = dialog.selected_backend
            worker = dialog.get_worker(backend)
            device = worker.device_by_name(dialog.selected_name) if worker else None
            if device is None:
                self.cast_btn.setChecked(False)
                QMessageBox.warning(
                    self, "Dispositivo no disponible", "No se pudo conectar con ese dispositivo."
                )
                return

            sesion = self._cast_session if backend == BACKEND_CHROMECAST else self._dlna_session
            try:
                sesion.connect(device)
                if local_path:
                    sesion.cast_local_file(local_path, title=title)
                else:
                    sesion.cast_url(url, content_type or "video/mp4", title=title)
                self.cast_btn.setChecked(True)
                self.statusBar().showMessage(f"Enviando «{title}» a {device.name}…", 6000)
            except Exception as exc:
                self.cast_btn.setChecked(False)
                sesion.disconnect()
                QMessageBox.warning(self, "Error al enviar a la TV", str(exc))
        finally:
            # Pase lo que pase (aceptar, cancelar o error), hay que cerrar el
            # explorador zeroconf: si no, cada búsqueda deja sockets abiertos.
            dialog.release_worker()

    def _make_list(self, reorderable: bool = False) -> QListWidget:
        lst = QListWidget()
        lst.setObjectName("channelList")
        lst.setItemDelegate(self.delegate)
        lst.setMouseTracking(True)
        lst.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lst.itemClicked.connect(lambda item, w=lst: self.playback.on_item_activated(item, w))
        lst.setContextMenuPolicy(Qt.CustomContextMenu)
        lst.customContextMenuRequested.connect(lambda pos, w=lst: self._show_context_menu(pos, w))
        if reorderable:
            # Solo Favoritos se puede reordenar a mano arrastrando filas --
            # el resto de listas reflejan un orden que viene de fuera (la
            # lista M3U, la API de radio, o la fecha del historial) y
            # reordenarlas a mano no se guardaría en ningún sitio.
            lst.setDragDropMode(QListWidget.InternalMove)
            lst.setDefaultDropAction(Qt.MoveAction)
            lst.model().rowsMoved.connect(lambda *_: self.lists.persist_favorites_order())
        return lst

    def _build_player_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 18, 20, 16)
        layout.setSpacing(12)

        self.player_frame = QFrame()
        self.player_frame.setObjectName("playerFrame")
        self.player_frame.installEventFilter(self)
        frame_layout = QVBoxLayout(self.player_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)

        self.player_stack = QStackedWidget()
        # QStackedWidget siempre ajusta a su widget hijo actual al tamaño
        # completo DEL PROPIO STACK — pero eso no significa que el stack en
        # sí crezca dentro de frame_layout. Sin esta línea, player_stack se
        # quedaba con la política Preferred por defecto de Qt y su sizeHint
        # (dominado por EqualizerWidget.setMinimumHeight(200)); el vídeo
        # salía correctamente escalado... al tamaño pequeño que Qt le daba
        # al stack, con el fondo de playerFrame visible alrededor.
        self.player_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player = VLCPlayer()
        self.player.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player.error_occurred.connect(self.playback.on_player_error)
        self.player.end_reached.connect(self.playback.on_player_end_reached)
        self._apply_saved_equalizer()
        self.equalizer = EqualizerWidget()
        self.player_stack.addWidget(self.player)
        self.player_stack.addWidget(self.equalizer)
        frame_layout.addWidget(self.player_stack, stretch=1)

        self.live_badge = QLabel("EN DIRECTO", self.player_stack)
        self.live_badge.setObjectName("liveBadge")
        set_variant(self.live_badge, "danger")
        self.live_badge.adjustSize()
        self.live_badge.move(14, 14)
        self.live_badge.hide()

        layout.addWidget(self.player_frame, stretch=1)
        self.now_playing_bar = self._build_now_playing_bar()
        layout.addWidget(self.now_playing_bar)

        return panel

    def set_live_badge_visible(self, visible: bool) -> None:
        """Sincroniza el indicador visual con la emisión actual."""
        self.live_badge.setVisible(bool(visible))
        if visible:
            self.live_badge.raise_()

    @staticmethod
    def _make_separator() -> QFrame:
        """
        Línea vertical fina entre grupos de botones de control. Antes todos
        los botones iban en una sola fila sin ninguna separación visual más
        que el spacing del layout — con el halo del play y poco espacio
        entre botones, la fila entera se veía como un bloque pegado en vez
        de controles agrupados por función (favorito/cast, reproducción,
        grabar/volumen, vista).
        """
        sep = QFrame()
        sep.setObjectName("ctrlSeparator")
        sep.setFixedWidth(1)
        sep.setFixedHeight(22)
        return sep

    @staticmethod
    def _make_glow(color: QColor, blur: float = 22, alpha: int = 160, y_offset: float = 0) -> QGraphicsDropShadowEffect:
        """
        Halo de color alrededor de un botón, vía QGraphicsDropShadowEffect
        (esto sí aplica a QWidgets normales, a diferencia de los delegados
        de lista, que no soportan QGraphicsEffect y necesitan pintarlo a mano).
        """
        effect = QGraphicsDropShadowEffect()
        glow_color = QColor(color)
        glow_color.setAlpha(alpha)
        effect.setColor(glow_color)
        effect.setBlurRadius(blur)
        effect.setOffset(0, y_offset)
        return effect

    def _build_now_playing_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("nowPlayingBar")
        bar.setFixedHeight(118)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        info_row = QHBoxLayout()
        self.now_logo = QLabel()
        self.now_logo.setFixedSize(44, 44)
        self.now_logo.setStyleSheet(f"background-color: {palette.BG_PANEL_ALT}; border-radius: 10px;")
        self.now_logo.setAlignment(Qt.AlignCenter)
        info_row.addWidget(self.now_logo)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.now_title = QLabel("Nada en reproducción")
        self.now_title.setObjectName("nowTitle")
        self.now_subtitle = QLabel("Elige un canal o una emisora")
        self.now_subtitle.setObjectName("nowSubtitle")
        text_col.addWidget(self.now_title)
        text_col.addWidget(self.now_subtitle)
        info_row.addLayout(text_col, stretch=1)

        # El volumen vivía en la fila de botones de abajo, donde con muchos
        # botones + separadores no queda sitio de sobra: con ventana
        # estrecha el slider (que necesita un ancho mínimo para no
        # convertirse en un punto suelto irreconocible) se comía a sus
        # vecinos. Aquí arriba, junto al nombre del canal, sí hay margen.
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.settings.get("volume", 80))
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(self.playback.on_volume_changed)
        info_row.addWidget(self.volume_slider)

        outer.addLayout(info_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        # Reorganizado en tres zonas (izquierda / centro / derecha), estilo
        # Spotify: antes todos los botones iban en una sola fila corrida de
        # izquierda a derecha sin agrupar por función. Con addStretch a cada
        # lado del grupo central, el transporte de reproducción (parar /
        # play / reintentar) queda siempre centrado en la barra pase lo que
        # pase con favoritos/cast a la izquierda o grabar/volumen/vista a la
        # derecha -- la misma jerarquía visual que un reproductor "grande".
        left_group = QHBoxLayout()
        left_group.setSpacing(8)
        center_group = QHBoxLayout()
        center_group.setSpacing(4)
        right_group = QHBoxLayout()
        right_group.setSpacing(6)

        self.fav_btn = QPushButton("\u2606")
        self.fav_btn.setObjectName("ctrlButton")
        self.fav_btn.setCheckable(True)
        self.fav_btn.clicked.connect(self.playback.toggle_favorite_current)
        left_group.addWidget(self.fav_btn)

        self.cast_btn = QPushButton()
        self.cast_btn.setObjectName("castButton")
        set_variant(self.cast_btn, "cast")
        self.cast_btn.setIconSize(QSize(18, 18))
        self.cast_btn.setIcon(app_icons.icon_cast(palette.ACCENT_CAST))
        self.cast_btn.setCheckable(True)
        self.cast_btn.setToolTip("Enviar a Chromecast / TV")
        self.cast_btn.clicked.connect(self._on_cast_live_clicked)
        self.cast_btn.toggled.connect(
            # "checked" pinta el icono con palette.BG_ROOT, igual que
            # #castButton[uiVariant="cast"]:checked en ui/style.py sobre el
            # fondo palette.ACCENT_CAST -- ver comentario equivalente en
            # tv_btn más arriba.
            lambda checked: self.cast_btn.setIcon(app_icons.icon_cast(palette.BG_ROOT if checked else palette.ACCENT_CAST))
        )
        # Mismo criterio que NAV_DOWNLOAD: Chromecast tampoco está incluido
        # en la versión free.
        self.cast_btn.setVisible(self.activated and not self.es_version_free)
        left_group.addWidget(self.cast_btn)

        self.stop_btn = QPushButton("\u25A0")
        self.stop_btn.setObjectName("ctrlButton")
        self.stop_btn.clicked.connect(self.playback.stop_playback)
        center_group.addWidget(self.stop_btn)

        center_group.addSpacing(4)
        self.play_btn = QPushButton("\u25B6")
        self.play_btn.setObjectName("playCircle")
        set_variant(self.play_btn, "primary")
        self.play_btn.clicked.connect(self.playback.toggle_play)
        center_group.addWidget(self.play_btn)
        center_group.addSpacing(4)

        self.retry_btn = QPushButton("\u21BB")
        self.retry_btn.setObjectName("ctrlButton")
        self.retry_btn.setToolTip("Reintentar conexión")
        self.retry_btn.clicked.connect(self.playback.retry_playback)
        self.retry_btn.setVisible(False)
        center_group.addWidget(self.retry_btn)

        self.record_btn = QPushButton("\u25CF")
        self.record_btn.setObjectName("recordButton")
        set_variant(self.record_btn, "danger")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.playback.toggle_recording)
        right_group.addWidget(self.record_btn)

        self.mute_btn = QPushButton()
        self.mute_btn.setObjectName("muteButton")
        set_variant(self.mute_btn, "info")
        self.mute_btn.setIconSize(QSize(18, 18))
        self.mute_btn.setIcon(app_icons.icon_speaker(palette.ACCENT_INFO, muted=False))
        self.mute_btn.setCheckable(True)
        self.mute_btn.clicked.connect(self.playback.toggle_mute)
        right_group.addWidget(self.mute_btn)

        right_group.addWidget(self._make_separator())

        # Pistas/pantalla completa/PiP/temporizador/cola: antes cada uno
        # tenia su propio boton circular en esta fila. Con 8 botones +
        # separador no cabian en ventanas estrechas y quedaban solapados o
        # cortados (reportado con captura). Se siguen creando igual -- el
        # resto del codigo (iconos, tooltips, estado checked/toggled) sigue
        # dependiendo de estos widgets como "guardianes de estado" -- pero
        # ya NO se anaden a right_group: se agrupan bajo un unico boton
        # "Mas opciones" siempre visible, asi la fila no crece con el
        # numero de funciones, solo con las acciones realmente frecuentes.
        self.tracks_btn = QPushButton("CC")
        self.tracks_btn.setObjectName("ctrlButton")
        self.tracks_btn.setToolTip("Pistas de audio y subt\u00EDtulos")
        self.tracks_btn.clicked.connect(self._open_tracks_menu)

        self.fullscreen_btn = QPushButton("\u26F6")
        self.fullscreen_btn.setObjectName("ctrlButton")
        self.fullscreen_btn.setToolTip("Pantalla completa (F11)")
        self.fullscreen_btn.clicked.connect(self.window_chrome.toggle_player_fullscreen)

        self.pip_btn = QPushButton()
        self.pip_btn.setObjectName("ctrlButton")
        self.pip_btn.setIconSize(QSize(18, 18))
        self.pip_btn.setIcon(app_icons.icon_pip(palette.TEXT_PRIMARY))
        self.pip_btn.setToolTip("Ventana flotante")
        self.pip_btn.clicked.connect(self.window_chrome.toggle_pip_mode)

        self.sleep_btn = QPushButton()
        self.sleep_btn.setObjectName("sleepButton")
        set_variant(self.sleep_btn, "sleep")
        self.sleep_btn.setIconSize(QSize(18, 18))
        self.sleep_btn.setIcon(app_icons.icon_moon(palette.ACCENT_SLEEP))
        self.sleep_btn.setCheckable(True)
        self.sleep_btn.setToolTip("Temporizador de apagado")
        self.sleep_btn.clicked.connect(self.playback.on_sleep_btn_clicked)
        self.sleep_btn.toggled.connect(
            # Mismo motivo que cast_btn: palette.BG_ROOT es el "color" que
            # usa #sleepButton[uiVariant="sleep"]:checked en ui/style.py
            # sobre el fondo palette.ACCENT_SLEEP.
            lambda checked: self.sleep_btn.setIcon(app_icons.icon_moon(palette.BG_ROOT if checked else palette.ACCENT_SLEEP))
        )

        self.queue_btn = QPushButton()
        self.queue_btn.setObjectName("ctrlButton")
        self.queue_btn.setIconSize(QSize(18, 18))
        self.queue_btn.setIcon(app_icons.icon_queue(palette.TEXT_PRIMARY))
        self.queue_btn.setToolTip("Cola de reproducción (vacía)")
        self.queue_btn.clicked.connect(self.queue.toggle_panel)

        self.more_btn = QPushButton()
        self.more_btn.setObjectName("ctrlButton")
        self.more_btn.setIconSize(QSize(18, 18))
        self.more_btn.setIcon(app_icons.icon_more(palette.TEXT_PRIMARY))
        self.more_btn.setToolTip("Más opciones (pistas, pantalla completa, PiP, temporizador, cola)")
        self.more_btn.clicked.connect(self._open_more_controls_menu)
        right_group.addWidget(self.more_btn)

        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self.playback.on_sleep_timeout)
        self._sleep_countdown = QTimer(self)
        self._sleep_countdown.setInterval(60000)   # cada minuto
        self._sleep_countdown.timeout.connect(self.playback.update_sleep_tooltip)
        self._sleep_minutes_left = 0

        controls.addLayout(left_group)
        controls.addStretch(1)
        controls.addLayout(center_group)
        controls.addStretch(1)
        controls.addLayout(right_group)

        outer.addLayout(controls)
        return bar

    def _open_more_controls_menu(self):
        """
        Menú "Más opciones" de la barra de reproducción: agrupa las
        acciones secundarias (pistas, pantalla completa, PiP, temporizador
        de apagado, cola) que antes tenían un botón circular propio en la
        fila de controles y dejaban de caber -- se solapaban o se veían
        cortados -- en ventanas estrechas. tracks_btn/fullscreen_btn/
        pip_btn/sleep_btn/queue_btn se siguen creando y actualizando en
        _build_now_playing_bar() exactamente igual que antes (iconos,
        tooltips, estado checked/toggled); solo dejaron de añadirse a la
        fila visible, así que aquí se reutilizan como fuente de su propio
        texto/estado en vez de duplicar esa lógica.
        """
        menu = QMenu(self)
        acento = self.settings.get("accent_color", palette.ACCENT)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {palette.BG_PANEL}; color: {palette.TEXT_PRIMARY}; "
            f"border: 1px solid {palette.BORDER}; }}"
            f"QMenu::item:selected {{ background-color: {acento}; color: {palette.BG_ROOT}; }}"
        )

        menu.addAction("Pistas de audio y subtítulos…", self._open_tracks_menu)

        texto_fullscreen = (
            "Salir de pantalla completa" if self._player_fullscreen
            else "Pantalla completa (F11)"
        )
        menu.addAction(texto_fullscreen, self.window_chrome.toggle_player_fullscreen)

        texto_pip = "Salir de ventana flotante" if self._pip_mode else "Ventana flotante"
        menu.addAction(texto_pip, self.window_chrome.toggle_pip_mode)

        menu.addSeparator()

        if self._sleep_timer.isActive():
            texto_sleep = f"Cancelar temporizador ({self._sleep_minutes_left} min restantes)"
        else:
            texto_sleep = "Temporizador de apagado…"
        # on_sleep_btn_clicked ya decide internamente si abre el selector
        # de minutos o cancela el temporizador activo -- no hace falta
        # duplicar esa rama aquí, solo el texto que se muestra.
        menu.addAction(texto_sleep, self.playback.on_sleep_btn_clicked)

        menu.addAction(self.queue_btn.toolTip(), self.queue.toggle_panel)

        menu.addSeparator()
        texto_audio_only = (
            "Desactivar modo solo audio (TV)" if self._audio_only_tv
            else "Modo solo audio (TV)…"
        )
        menu.addAction(texto_audio_only, self.playback.toggle_audio_only_tv)
        menu.addAction("Ecualizador…", self._open_equalizer_dialog)

        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def _open_tracks_menu(self):
        """
        Menú de pistas de audio y subtítulos del stream actual (solo TV:
        las emisoras de radio no traen subtítulos y casi nunca más de una
        pista de audio). Se construye cada vez que se abre, no una vez al
        arrancar, porque las pistas disponibles dependen del canal que
        esté sonando en ese momento.
        """
        if self.current_type != "tv" or not self.player.disponible:
            QMessageBox.information(
                self, "Sin pistas disponibles",
                "Las pistas de audio y subtítulos solo están disponibles "
                "mientras se reproduce un canal de TV."
            )
            return

        menu = QMenu(self)
        acento = self.settings.get("accent_color", palette.ACCENT)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {palette.BG_PANEL}; color: {palette.TEXT_PRIMARY}; "
            f"border: 1px solid {palette.BORDER}; }}"
            f"QMenu::item:selected {{ background-color: {acento}; color: {palette.BG_ROOT}; }}"
        )

        audio_menu = menu.addMenu("Pista de audio")
        pistas_audio = self.player.audio_tracks()
        if not pistas_audio:
            audio_menu.addAction("(Solo una pista disponible)").setEnabled(False)
        else:
            actual = self.player.current_audio_track()
            for track_id, nombre in pistas_audio:
                accion = audio_menu.addAction(nombre)
                accion.setCheckable(True)
                accion.setChecked(track_id == actual)
                accion.triggered.connect(lambda _c=False, tid=track_id: self.player.set_audio_track(tid))

        subs_menu = menu.addMenu("Subtítulos")
        pistas_subs = self.player.subtitle_tracks()
        if not pistas_subs:
            subs_menu.addAction("(Este stream no trae subtítulos)").setEnabled(False)
        else:
            actual_sub = self.player.current_subtitle_track()
            for track_id, nombre in pistas_subs:
                accion = subs_menu.addAction(nombre)
                accion.setCheckable(True)
                accion.setChecked(track_id == actual_sub)
                accion.triggered.connect(lambda _c=False, tid=track_id: self.player.set_subtitle_track(tid))

        # Se ancla a more_btn (no a tracks_btn): tracks_btn ya no vive en
        # ningún layout visible -- ver el comentario en _build_now_playing_bar
        # -- así que su propia posición en pantalla no sería fiable.
        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def _build_title_bar(self) -> QWidget:
        """
        Barra de título propia. Antes esto se montaba con los 'corner widgets'
        de QMenuBar, un mecanismo cuyo dibujado depende del estilo nativo y
        que en algunos equipos no llegaba a mostrarse. Aquí la disposición es
        explícita, así que se ve igual en cualquier máquina.
        """
        barra = QWidget()
        barra.setObjectName("titleBar")
        barra.setFixedHeight(38)

        fila = QHBoxLayout(barra)
        fila.setContentsMargins(12, 0, 6, 0)
        fila.setSpacing(10)

        marca = QLabel(f"TDT & Radio VIP  ·  {cfg.APP_VERSION}")
        marca.setObjectName("titleBrand")
        fila.addWidget(marca)

        fila.addWidget(self._build_menu())

        # Zona vacía: es la que permite arrastrar la ventana.
        fila.addStretch(1)

        min_btn = QToolButton()
        min_btn.setObjectName("winCtrlButton")
        min_btn.setText("\u2013")
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.setToolTip("Minimizar")
        min_btn.clicked.connect(self.showMinimized)
        fila.addWidget(min_btn)

        self._maximize_btn = QToolButton()
        self._maximize_btn.setObjectName("winCtrlButton")
        self._maximize_btn.setText("\u25A1")
        self._maximize_btn.setCursor(Qt.PointingHandCursor)
        self._maximize_btn.setToolTip("Maximizar")
        self._maximize_btn.clicked.connect(self.window_chrome.toggle_maximize)
        fila.addWidget(self._maximize_btn)

        close_btn = QToolButton()
        close_btn.setObjectName("winCloseButton")
        close_btn.setText("\u00D7")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("Cerrar")
        close_btn.clicked.connect(self.close)
        fila.addWidget(close_btn)

        barra.installEventFilter(self)
        return barra

    def _build_menu(self) -> QMenuBar:
        menu = QMenuBar()
        menu.setObjectName("appMenuBar")
        menu.setNativeMenuBar(False)
        self.menu_bar = menu

        file_menu = menu.addMenu("Archivo")
        global_search_action = QAction("Búsqueda global…", self)
        global_search_action.setShortcut(QKeySequence("Ctrl+K"))
        global_search_action.triggered.connect(self._open_command_palette)
        file_menu.addAction(global_search_action)
        file_menu.addSeparator()

        refresh_tv_action = QAction("Actualizar canales TV", self)
        refresh_tv_action.triggered.connect(lambda: self._load_tv_channels(force=True))
        file_menu.addAction(refresh_tv_action)

        refresh_radio_action = QAction("Actualizar emisoras de radio", self)
        refresh_radio_action.triggered.connect(lambda: self._load_radio_stations(force=True))
        file_menu.addAction(refresh_radio_action)

        file_menu.addSeparator()
        add_entry_action = QAction("Añadir canal o emisora…", self)
        add_entry_action.triggered.connect(self.library.open_add_entry_dialog)
        file_menu.addAction(add_entry_action)

        import_action = QAction("Importar lista M3U…", self)
        import_action.triggered.connect(self.library.open_import_playlist_dialog)
        file_menu.addAction(import_action)

        manage_action = QAction("Gestionar canales personalizados…", self)
        manage_action.triggered.connect(lambda: self.library.open_manage_channels_dialog())
        file_menu.addAction(manage_action)

        file_menu.addSeparator()
        recurring_action = QAction("Grabaciones recurrentes…", self)
        recurring_action.triggered.connect(self._open_recurring_dialog)
        file_menu.addAction(recurring_action)

        mosaic_action = QAction("Multivista (mosaico)…", self)
        mosaic_action.triggered.connect(self._open_mosaic_view)
        file_menu.addAction(mosaic_action)

        file_menu.addSeparator()
        export_backup_action = QAction("Exportar copia de seguridad…", self)
        export_backup_action.triggered.connect(self.library.export_backup)
        file_menu.addAction(export_backup_action)

        import_backup_action = QAction("Importar copia de seguridad…", self)
        import_backup_action.triggered.connect(self.library.import_backup)
        file_menu.addAction(import_backup_action)

        file_menu.addSeparator()
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        settings_menu = menu.addMenu("Configuración")
        settings_action = QAction("Preferencias…", self)
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        help_menu = menu.addMenu("Ayuda")
        about_action = QAction("Acerca de", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        stats_action = QAction("Estadísticas de uso…", self)
        stats_action.triggered.connect(self._open_stats_dialog)
        help_menu.addAction(stats_action)

        update_action = QAction("Buscar actualizaciones", self)
        update_action.triggered.connect(self._check_for_update)
        help_menu.addAction(update_action)

        logs_action = QAction("Abrir carpeta de logs", self)
        logs_action.triggered.connect(self._abrir_carpeta_logs)
        help_menu.addAction(logs_action)

        return menu

    def _open_command_palette(self):
        """
        Búsqueda global (Ctrl+K / menú Archivo). Las "acciones rápidas" se
        arman aquí, no dentro de CommandPalette, para que ese módulo no
        tenga que importar NAV_HOME/NAV_TV/etc. de este archivo (crearía un
        import circular, ya que este archivo importa CommandPalette).
        """
        acciones = [
            ("Preferencias…", self._open_settings),
            ("Ir a Inicio", lambda: self.nav_group.button(NAV_HOME).click()),
            ("Ir a Televisión", lambda: self.nav_group.button(NAV_TV).click()),
            ("Ir a Radio", lambda: self.nav_group.button(NAV_RADIO).click()),
            ("Ir a Favoritos", lambda: self.nav_group.button(NAV_FAV).click()),
            ("Ir a Historial", lambda: self.nav_group.button(NAV_HIST).click()),
            ("Añadir canal o emisora…", self.library.open_add_entry_dialog),
            ("Importar lista M3U…", self.library.open_import_playlist_dialog),
            ("Gestionar canales personalizados…", lambda: self.library.open_manage_channels_dialog()),
        ]
        if self.activated and not self.es_version_free:
            acciones.append(("Ir a Descargas", lambda: self.nav_group.button(NAV_DOWNLOAD).click()))

        dialog = CommandPalette(self, acciones)
        dialog.show_centered()

    def eventFilter(self, obj, event):
        """
        Delega en WindowChrome (arrastre de ventana, maximizar/restaurar,
        doble clic para pantalla completa). WindowChrome devuelve None
        cuando el evento no le interesa -- Qt exige entonces caer al
        comportamiento por defecto de QMainWindow, no un True/False propio.
        """
        result = self.window_chrome.event_filter(obj, event)
        if result is None:
            return super().eventFilter(obj, event)
        return result

    # Maximizar/restaurar, pantalla completa y modo PiP (antes _toggle_maximize
    # / _maximizar / _restaurar_tamano / _toggle_player_fullscreen /
    # _salir_fullscreen_si_activo / _toggle_pip_mode / _enter_pip_mode /
    # _exit_pip_mode / _enter_player_fullscreen / _exit_player_fullscreen)
    # viven ahora en ui.window_chrome.WindowChrome (self.window_chrome).

    # ---------- Temporizador de apagado ----------

    # El temporizador de apagado (antes _on_sleep_btn_clicked / _iniciar_sleep /
    # _cancelar_sleep / _update_sleep_tooltip / _on_sleep_timeout) vive ahora en
    # ui.playback_controller.PlaybackController -- ver self.playback mas arriba.

    def _registrar_atajos(self):
        """
        Atajos a nivel de ventana. Con keyPressEvent no bastaba: si el foco
        estaba en el campo de URL o en la lista de canales, el widget hijo se
        quedaba la pulsación y F11/Esc no llegaban nunca a la ventana.
        """
        atajo_fs = QShortcut(QKeySequence(Qt.Key_F11), self)
        atajo_fs.setContext(Qt.WindowShortcut)
        atajo_fs.activated.connect(self.window_chrome.toggle_player_fullscreen)

        atajo_salir = QShortcut(QKeySequence(Qt.Key_Escape), self)
        atajo_salir.setContext(Qt.WindowShortcut)
        atajo_salir.activated.connect(self.window_chrome.salir_fullscreen_si_activo)


    # ---------- Navegación ----------

    def showEvent(self, event):
        super().showEvent(event)
        # La ventana ya tiene HWND en este punto.
        if not self._native_icon_applied:
            self._native_icon_applied = True
            icon_path = cfg.get_icon_path()
            if icon_path:
                set_native_window_icon(int(self.winId()), icon_path)

        if not self._taskbar._ready:
            hwnd = int(self.winId())
            if self._taskbar.setup(hwnd):
                self._taskbar.bind(BTN_PREV, self.playback.play_prev)
                self._taskbar.bind(BTN_PLAY, self.playback.toggle_play)
                self._taskbar.bind(BTN_STOP, self.playback.stop_playback)
                self._taskbar.bind(BTN_MUTE, self.playback.toggle_mute)
                self._taskbar.bind(BTN_NEXT, self.playback.play_next)

    # _play_prev / _play_next viven ahora en PlaybackController (self.playback).

    def nativeEvent(self, eventType, message):
        """
        Enruta los mensajes nativos de Windows hacia TaskbarControls, para
        que los clics en los botones de la miniatura de la barra de tareas
        (prev/play/stop/mute/next al pasar el ratón por el icono) lleguen a
        algún sitio. Sin este método, TaskbarControls.on_windows_message()
        no lo llamaba nadie -- estaba escrito pero nunca conectado.
        """
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                if self._taskbar.on_native_message(int(message)):
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def _on_nav_changed(self, nav_id: int):
        self.stack.setCurrentIndex(nav_id)
        self.section_title.setText(SECTION_TITLES[nav_id])
        self.section_title.setStyleSheet("")
        set_variant(self.section_title, SECTION_VARIANTS[nav_id])
        self.epg_btn.setVisible(nav_id == NAV_TV)
        self.tv_view_toggle.setVisible(nav_id == NAV_TV)
        self.group_filter.setVisible(nav_id in (NAV_TV, NAV_FAV))
        if nav_id == NAV_TV:
            self.lists.refresh_group_filter()
        elif nav_id == NAV_FAV:
            self.lists.refresh_folder_filter()
        elif nav_id == NAV_HOME:
            self._refresh_home_page()
        self.search_box.setVisible(nav_id not in (NAV_DOWNLOAD, NAV_HOME))
        self.search_box.clear()
        if nav_id not in (NAV_DOWNLOAD, NAV_HOME):
            self.lists.filter_current_list()
        self._animate_page(self.stack.currentWidget())

    def _animate_page(self, widget: QWidget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    # ---------- Carga de datos ----------

    def _load_tv_channels(self, force: bool = False):
        if self._is_closing:
            return
        self.statusBar().showMessage("Cargando canales de TV…")
        url = self.settings.get("tv_playlist_url") or tv_channels.playlist_url_for(
            self.settings.get("tv_country_code", "ES")
        )
        worker = FetchWorker(tv_channels.fetch_tv_channels, url, force)
        worker.done.connect(self._on_tv_channels_loaded)
        self._tv_worker = worker
        worker.start()

    def _on_tv_channels_loaded(self, channels):
        if self._is_closing:
            return
        channels = channels or []
        # filter_hidden(): canales de la lista pública que el usuario pidió
        # ocultar desde Archivo > Gestionar canales personalizados (ver
        # core.channels.hide_channels) -- se aplica solo a la lista pública,
        # no a la personalizada, porque no tendría sentido ocultar algo que
        # el usuario añadió él mismo a mano.
        channels = tv_channels.filter_hidden(channels)
        custom = tv_channels.load_custom_channels()
        # dedupe_channels(): la lista del país (o la URL personalizada de
        # Configuración) y la lista de canales importados a mano pueden
        # perfectamente compartir canales -- "La 1"/"La 2" suelen venir en
        # cualquier lista española, así que si además se importó una
        # lista propia con esos mismos canales, salían duplicados en
        # pantalla (uno de cada fuente) aunque cada lista por separado ya
        # viniera limpia.
        self.tv_channels_data = tv_channels.dedupe_channels(channels + custom)
        self.lists.refresh_group_filter()
        self.lists.populate_tv_list(self.tv_channels_data)
        self.statusBar().showMessage(f"{len(self.tv_channels_data)} canales de TV cargados.", 5000)

    # _refresh_folder_filter / _refresh_group_filter viven ahora en
    # ChannelListsController (self.lists).

    def _load_radio_stations(self, force: bool = False):
        if self._is_closing:
            return
        self.statusBar().showMessage("Cargando emisoras de radio…")
        worker = FetchWorker(
            radio_stations.fetch_radio_stations, self.settings.get("radio_country_code", "ES"), 250, force
        )
        worker.done.connect(self._on_radio_stations_loaded)
        self._radio_worker = worker
        worker.start()

    def _on_radio_stations_loaded(self, stations):
        if self._is_closing:
            return
        stations = stations or []
        stations = radio_stations.filter_hidden(stations)  # ver _on_tv_channels_loaded
        custom = radio_stations.load_custom_stations()
        self.radio_stations_data = stations + custom
        self.lists.populate_radio_list(self.radio_stations_data)
        self.statusBar().showMessage(f"{len(self.radio_stations_data)} emisoras de radio cargadas.", 5000)

    # _open_epg_dialog / _tune_to_tvg_id / _load_epg / _on_epg_loaded viven
    # ahora en ui.epg_controller.EpgController (self.epg).

    def _open_recurring_dialog(self):
        RecurringRecordingsDialog(self, self.tv_channels_data).exec()

    def _open_mosaic_view(self):
        if not self.tv_channels_data:
            QMessageBox.information(
                self, "Multivista", "Espera a que carguen los canales de TV."
            )
            return

        # La multivista abre hasta 4 instancias de VLC en paralelo (ver
        # ui/mosaic_view.py) -- sumadas a la del reproductor principal, son
        # 5 streams compitiendo a la vez por el dispositivo de audio, que en
        # Windows es lo que dejaba mudo al canal principal al cerrar la
        # multivista (seguía "reproduciendo" pero sin sonido, y hacía falta
        # reiniciar la app). Se para del todo mientras el diálogo está
        # abierto -- no se ve de todas formas, tapa la ventana entera -- y
        # se retoma desde cero (media_player limpio, ver VLCPlayer.play) al
        # cerrarlo.
        reanudar = None
        if self.current_url:
            reanudar = (
                self.current_type, self.current_name, self.current_url,
                self.current_tvg_id, self.current_logo,
            )
            self.player.stop()
            self.equalizer.stop()

        MosaicView(self, self.tv_channels_data).exec()

        if reanudar is not None:
            self.playback.play(*reanudar)

    def _open_stats_dialog(self):
        StatsDialog(self).exec()

    def _check_for_update(self):
        """
        Comprobación manual desde Ayuda > Buscar actualizaciones. Solo
        avisa y ofrece abrir la página de descarga -- no descarga ni
        reemplaza nada sola (ver core/updater.py para el porqué).
        """
        if self._is_closing:
            return
        url = self.settings.get("update_check_url", "")
        if not url:
            QMessageBox.information(
                self, "Buscar actualizaciones",
                "La comprobación de actualizaciones no está configurada en esta instalación.",
            )
            return
        self.statusBar().showMessage("Comprobando actualizaciones…", 4000)
        worker = FetchWorker(updater.check_for_update, url, cfg.APP_VERSION)
        worker.done.connect(self._on_update_check_done)
        self._update_check_worker = worker
        worker.start()

    def _on_update_check_done(self, resultado):
        if self._is_closing:
            return
        if not resultado:
            QMessageBox.information(
                self, "Buscar actualizaciones", "Ya tienes la versión más reciente."
            )
            return
        version = resultado.get("version", "?")
        enlace = resultado.get("url", "")
        respuesta = QMessageBox.question(
            self, "Actualización disponible",
            f"Hay una versión nueva disponible: {version} "
            f"(la instalada es {cfg.APP_VERSION}).\n\n¿Abrir la página de descarga?",
        )
        if respuesta == QMessageBox.Yes and enlace:
            QDesktopServices.openUrl(QUrl(enlace))

    # ---------- Añadir canal/emisora manual e importar listas M3U ----------
    #
    # _open_add_entry_dialog / _edit_custom_entry / _delete_custom_entry /
    # _open_import_playlist_dialog / _fetch_playlist_text / _on_playlist_fetched /
    # _exportar_backup / _importar_backup viven ahora en
    # ui.library_controller.LibraryController (self.library).

    # ---------- Poblar listas ----------

    # _request_logo / _populate_tv_list / _populate_radio_list /
    # _refresh_favorites_tab / _refresh_history_tab / _mark_playing_everywhere /
    # _mark_favorites_everywhere / _filter_current_list viven ahora en
    # ChannelListsController (self.lists).

    # ---------- Reproducción ----------

    # _on_item_activated / _activate_item / _auto_skip_next viven ahora en
    # PlaybackController (self.playback).

    def _show_context_menu(self, pos, list_widget: QListWidget):
        item = list_widget.itemAt(pos)
        if not item:
            return
        data = item.data(ROLE_DATA) or {}
        if not data.get("name"):
            return
        is_custom = bool(item.data(ROLE_CUSTOM))
        is_fav = fav_store.is_favorite(self.favorites, data.get("type"), data.get("name"))

        menu = QMenu(self)
        play_action = menu.addAction("\u25B6 Reproducir")
        queue_action = menu.addAction("Añadir a la cola")
        fav_action = menu.addAction("\u2605 Quitar de favoritos" if is_fav else "\u2606 Añadir a favoritos")
        folder_action = None
        if is_fav:
            folder_action = menu.addAction("Mover a carpeta…")
        edit_action = delete_action = None
        if is_custom:
            menu.addSeparator()
            edit_action = menu.addAction("Editar…")
            delete_action = menu.addAction("Eliminar")

        chosen = menu.exec(list_widget.viewport().mapToGlobal(pos))
        if chosen == play_action:
            self.playback.activate_item(item, list_widget, is_auto=False)
        elif chosen == queue_action:
            self.queue.add(data)
        elif chosen == fav_action:
            self._toggle_favorite_for(data)
        elif folder_action is not None and chosen == folder_action:
            self._mover_a_carpeta(data)
        elif edit_action is not None and chosen == edit_action:
            self.library.edit_custom_entry(data)
        elif delete_action is not None and chosen == delete_action:
            self.library.delete_custom_entry(data)

    def _mover_a_carpeta(self, data: dict):
        carpetas = fav_store.get_folders(self.favorites)
        opciones = ["(Sin carpeta)"] + carpetas + ["+ Nueva carpeta…"]
        carpeta_actual = next(
            (f.get("folder", "") for f in self.favorites
             if f.get("type") == data.get("type") and f.get("name") == data.get("name")),
            "",
        )
        idx_actual = opciones.index(carpeta_actual) if carpeta_actual in opciones else 0
        elegido, ok = QInputDialog.getItem(
            self, "Mover a carpeta",
            f"Carpeta para «{data.get('name', '')}»:",
            opciones, idx_actual, editable=False,
        )
        if not ok:
            return

        if elegido == "+ Nueva carpeta…":
            nombre, ok2 = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
            if not ok2 or not nombre.strip():
                return
            nueva_carpeta = nombre.strip()
        elif elegido == "(Sin carpeta)":
            nueva_carpeta = ""
        else:
            nueva_carpeta = elegido

        self.favorites = fav_store.set_favorite_folder(data["type"], data["name"], nueva_carpeta)
        self.lists.refresh_favorites_tab()
        if self.stack.currentWidget() is self.fav_list:
            self.lists.refresh_folder_filter()

    def _toggle_favorite_for(self, data: dict):
        self.favorites = fav_store.toggle_favorite(
            data.get("type"), data.get("name"), data.get("url", ""), data.get("logo", "")
        )
        self.lists.refresh_favorites_tab()
        self.lists.mark_favorites_everywhere()
        if self.current_type == data.get("type") and self.current_name == data.get("name"):
            self.fav_btn.setChecked(fav_store.is_favorite(self.favorites, data.get("type"), data.get("name")))
            self.fav_btn.setText("\u2605" if self.fav_btn.isChecked() else "\u2606")

    # _play / _update_now_logo / _toggle_play / _on_player_error /
    # _on_player_end_reached / _retry_playback / _stop_playback /
    # _on_volume_changed / _toggle_mute / _toggle_favorite_current /
    # _toggle_recording / _update_epg_display viven ahora en
    # PlaybackController (self.playback).

    # ---------- Configuración ----------

    def _open_settings(self):
        old_tv_url = self.settings.get("tv_playlist_url") or tv_channels.playlist_url_for(
            self.settings.get("tv_country_code", "ES")
        )
        old_radio_country = self.settings.get("radio_country_code", "ES")
        old_accent = self.settings.get("accent_color", palette.ACCENT)
        old_profile = self.settings.get("active_profile", "Default")
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            new_settings = dialog.get_settings()
            if not cfg.save_settings(new_settings):
                QMessageBox.warning(
                    self,
                    "No se pudieron guardar los ajustes",
                    "No se pudieron guardar los ajustes. Inténtalo de nuevo.",
                )
                return
            self.settings = new_settings

            new_profile = self.settings.get("active_profile", "Default")
            if new_profile != old_profile:
                QMessageBox.information(
                    self, "Perfil cambiado",
                    f"Perfil activo: {new_profile}.\n\n"
                    "Cierra y vuelve a abrir la aplicación para que se aplique del todo."
                )
            self.recorder = rec_module.Recorder(self.downloads_dir)
            if self.settings.get("epg_url"):
                self.epg.load()

            new_accent = self.settings.get("accent_color", palette.ACCENT)
            if new_accent != old_accent:
                app = QApplication.instance()
                if app is not None:
                    app.setStyleSheet(build_style(new_accent))

            new_tv_url = self.settings.get("tv_playlist_url") or tv_channels.playlist_url_for(
                self.settings.get("tv_country_code", "ES")
            )
            if new_tv_url != old_tv_url:
                self._load_tv_channels()
            if self.settings.get("radio_country_code", "ES") != old_radio_country:
                self._load_radio_stations()

    def _abrir_carpeta_logs(self):
        carpeta = log_file_path().parent
        carpeta.mkdir(parents=True, exist_ok=True)
        os.startfile(carpeta)

    def _show_about(self):
        if self.es_version_free:
            registro_html = (
                f"<p style='font-size:13pt; font-weight:700; color:{palette.ACCENT_INFO};'>"
                "Versión FREE — TV y Radio incluidos, sin Descargas ni Chromecast</p>"
            )
        elif self.activated:
            registro_html = (
                f"<p style='font-size:13pt; font-weight:700; color:{palette.SUCCESS};'>"
                "Aplicación registrada</p>"
            )
        else:
            registro_html = (
                f"<p style='font-size:13pt; font-weight:700; color:{palette.DANGER};'>"
                "Versión no activada</p>"
            )
        QMessageBox.about(
            self, "Acerca de",
            f"<b>TDT & Radio VIP</b> — versión {cfg.APP_VERSION}<br>"
            "Coder By X@R<br><br>"
            f"{registro_html}"
            "Reproductor de canales de TDT y radio online gratuitos.<br>"
            "Fuentes: iptv-org (TV) y Radio-Browser (radio).<br><br>"
            "La disponibilidad y calidad de los streams depende de terceros ajenos a esta aplicación.<br><br>"
            "<hr>"
            f"<b style='color:{palette.ACCENT};'>&#10084; Besitos a Evelyn Llamas &#10084;</b><br>"
            "Saludos a mi amigo Paco Blanco.<br>"
            "Viva La Guardia Civil — SANCHEZ CABRON:<br>"
            "<b>¡España Campeona del Mundo! "
            "<img src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB4AAAAUCAIAAAAVyRqTAAAALUlEQVR4nGNcJSrNQBvARCNzR43GBIwf99PK6KEZIKNGjxo9YEYzjhaqw8FoABs0A4rK4LUlAAAAAElFTkSuQmCC' width='24' height='16'> "
            "&#127942; &#128170; ¡OLÉ, LA UCO!</b><br><br>"
            "Ceuta y Melilla Españolas siempre!. "
            "<img src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB4AAAAUCAIAAAAVyRqTAAAALUlEQVR4nGNcJSrNQBvARCNzR43GBIwf99PK6KEZIKNGjxo9YEYzjhaqw8FoABs0A4rK4LUlAAAAAElFTkSuQmCC' width='24' height='16'>"
        )

    def closeEvent(self, event):
        if self._is_closing:
            event.ignore()
            return
        self._is_closing = True
        FetchWorker.begin_shutdown()
        reminder_timer = getattr(self, "_reminder_timer", None)
        if reminder_timer is not None:
            reminder_timer.stop()
        self._tray_icon.hide()
        self._media_keys.stop()
        if self.recorder.is_recording:
            # on_wait bombea eventos sin entrada de usuario: sin esto, cerrar la app
            # con una grabación en curso bloqueaba el hilo de la interfaz
            # mientras ffmpeg terminaba de cerrar el archivo -- Windows
            # llegaba a marcar la ventana como "no responde" antes de que
            # terminara. Ver core.recorder.Recorder.stop().
            self.recorder.stop(on_wait=process_events_during_shutdown)
            if self._scheduled_recording_active is not None:
                rec = self._scheduled_recording_active
                recording_schedule.mark_done(rec.tvg_id, rec.title, rec.start)
                self._scheduled_recording_active = None
        self.player.stop()
        self.equalizer.stop()
        self._cast_session.disconnect()
        self._dlna_session.disconnect()
        # on_wait: ver el comentario del recorder.stop() más arriba -- mismo
        # motivo, esta vez para que apagar aria2c.exe (si había torrents
        # activos) no bloquee la interfaz y deje el proceso huérfano si
        # Windows fuerza el cierre antes de que termine.
        self.download_panel.shutdown(on_wait=process_events_during_shutdown)
        self._taskbar.cleanup()
        shutdown_workers(FetchWorker.active_workers())
        self.player.release()
        event.accept()

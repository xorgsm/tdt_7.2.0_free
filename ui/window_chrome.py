"""
Controlador de "cromado" de ventana de TDT & Radio VIP: arrastre de la
barra de título propia (sin bordes nativos de Windows), maximizar/
restaurar, pantalla completa del reproductor y modo ventana flotante
(picture-in-picture).

Extraído de ui/main_window.py por el mismo motivo que
ui.playback_controller.PlaybackController — ver el docstring de ese
módulo. Igual que allí, el estado y los widgets siguen viviendo en
MainWindow (self.win); este módulo agrupa el comportamiento de
"cromado de ventana", que antes vivía mezclado con reproducción, listas
de canales y el resto de secciones dentro de una única clase de más de
2.000 líneas.

Nota sobre eventFilter: Qt exige que el objeto pasado a
installEventFilter() sea el mismo objeto cuyo método eventFilter() se
invoca — por eso MainWindow conserva un eventFilter() propio (obligatorio,
no se puede mover), que delega aquí en event_filter().

Coder By X@R
"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication

from ui import icons as app_icons
from ui import palette
from ui.style import accent_shades


class WindowChrome:
    """Arrastre de ventana, maximizar/restaurar, fullscreen y PiP."""

    def __init__(self, window):
        self.win = window

    # ---------- Arrastre de la barra de título / fullscreen por doble clic ----------

    def event_filter(self, obj, event):
        win = self.win
        if obj is win.title_bar:
            # Los clics sobre el menú o sobre los botones los recibe cada uno
            # de esos widgets, así que aquí solo llegan los de la zona vacía:
            # exactamente donde tiene sentido arrastrar la ventana.
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.toggle_maximize()
                return True
            return self._handle_drag_event(event)
        elif obj is win.player_frame:
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.toggle_player_fullscreen()
                return True
        elif obj is win.library_sidebar:
            # Fondo vacío del sidebar de biblioteca (Recientes/Playlists):
            # arrastra la ventana igual que la barra de título. Pensado
            # para cuando este panel está abierto y ocupa buena parte de
            # la altura de la ventana -- sin esto, la única zona de
            # arrastre seguía siendo la franja fina de arriba del todo.
            return self._handle_drag_event(event)
        elif obj is win.library_sidebar.recent_list.viewport():
            return self._drag_from_list_background(win.library_sidebar.recent_list, event)
        elif obj is win.library_sidebar.playlists_list.viewport():
            return self._drag_from_list_background(win.library_sidebar.playlists_list, event)
        return None

    def _handle_drag_event(self, event):
        """
        Arrastre de ventana genérico a partir de un evento de ratón, sin el
        doble clic de maximizar (eso solo tiene sentido en la barra de
        título de verdad) -- extraído de la barra de título para
        reutilizarlo también en el fondo del sidebar de biblioteca (ver
        event_filter() y _drag_from_list_background()).

        Antes esto reposicionaba la ventana a mano en cada MouseMove
        (win.move() + win.repaint()). Con ventana sin marco +
        WA_TranslucentBackground + el HWND nativo de vídeo de libVLC
        embebido dentro, ese arrastre "a pulso" competía con cómo DWM
        compone la ventana en Windows: durante un arrastre rápido, distintas
        zonas (controles, sidebar, vídeo) podían recomponerse en instantes
        ligeramente distintos y quedar mezcladas -- huecos vacíos o
        contenido "fantasma" de la posición anterior, como se ve en la
        captura que reportó Xor. Pedirle a Qt/Windows que mueva la ventana
        con su propio bucle nativo (startSystemMove()) delega todo el
        arrastre al gestor de ventanas: es la misma ruta que usa cualquier
        ventana con barra de título nativa, así que compone exactamente
        igual de bien -- sin el tearing de ir empujando move() a mano.
        """
        win = self.win
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if win._pseudo_maximizado:
                # Arrastrar una ventana maximizada la restaura y la
                # "engancha" al cursor, como en cualquier app de Windows --
                # ahora se calcula una sola vez al pulsar, no en cada
                # MouseMove, porque el resto del arrastre lo lleva el SO.
                cursor = event.globalPosition().toPoint()
                ancho_previo = win.width()
                proporcion = cursor.x() / max(1, ancho_previo)
                self.restaurar_tamano()
                win.move(cursor.x() - int(win.width() * proporcion), win.y())
            handle = win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return True
        return None

    def _drag_from_list_background(self, list_widget, event):
        """
        Igual que _handle_drag_event, pero solo cuando el clic cae en el
        hueco vacío de un QListWidget (sin ningún elemento bajo el
        cursor) -- así "Recientes"/"Playlists" siguen funcionando con
        normalidad (clic, selección) y solo el espacio en blanco de
        debajo de las entradas sirve para arrastrar la ventana.
        """
        if (
            event.type() == QEvent.MouseButtonPress
            and list_widget.itemAt(event.position().toPoint()) is not None
        ):
            return None  # clic sobre una entrada real: comportamiento normal
        return self._handle_drag_event(event)

    # ---------- Maximizar / restaurar ----------

    def toggle_maximize(self):
        if self.win._pseudo_maximizado:
            self.restaurar_tamano()
        else:
            self.maximizar()

    def maximizar(self):
        win = self.win
        pantalla = win.screen() or QGuiApplication.primaryScreen()
        if pantalla is None:
            return
        win._geometria_normal = win.geometry()
        win._pseudo_maximizado = True
        # availableGeometry() excluye la barra de tareas; geometry() no.
        win.setGeometry(pantalla.availableGeometry())
        win._maximize_btn.setText("❐")
        win._maximize_btn.setToolTip("Restaurar")

    def restaurar_tamano(self):
        win = self.win
        win._pseudo_maximizado = False
        if win._geometria_normal is not None:
            win.setGeometry(win._geometria_normal)
        win._maximize_btn.setText("□")
        win._maximize_btn.setToolTip("Maximizar")

    # ---------- Pantalla completa del reproductor ----------

    def toggle_player_fullscreen(self):
        win = self.win
        if win._pip_mode:
            self.exit_pip_mode()
        if win._player_fullscreen:
            self.exit_player_fullscreen()
        else:
            self.enter_player_fullscreen()

    def salir_fullscreen_si_activo(self):
        win = self.win
        if win._player_fullscreen:
            self.exit_player_fullscreen()
        elif win._pip_mode:
            self.exit_pip_mode()

    def enter_player_fullscreen(self):
        win = self.win
        win._player_fullscreen = True
        win._was_maximized_before_fs = win._pseudo_maximizado

        win.nav_rail.setVisible(False)
        win.content_widget.setVisible(False)
        win.library_sidebar.setVisible(False)
        win.title_bar.setVisible(False)
        win.statusBar().setVisible(False)
        win.fullscreen_btn.setText("✕")
        win.fullscreen_btn.setToolTip("Salir de pantalla completa (Esc)")
        win.showFullScreen()

    def exit_player_fullscreen(self):
        win = self.win
        win._player_fullscreen = False

        win.nav_rail.setVisible(True)
        win.content_widget.setVisible(True)
        # Respeta la preferencia del usuario (botón de biblioteca del riel)
        # en vez de forzarlo visible: si lo había ocultado antes de entrar
        # en pantalla completa, debe seguir oculto al salir.
        win.library_sidebar.setVisible(win.library_toggle_btn.isChecked())
        win.title_bar.setVisible(True)
        win.statusBar().setVisible(True)

        win.fullscreen_btn.setText("⛶")
        win.fullscreen_btn.setToolTip("Pantalla completa (F11)")

        win.showNormal()
        if win._was_maximized_before_fs:
            win._pseudo_maximizado = False  # forzar recálculo limpio
            self.maximizar()

    # ---------- Ventana flotante (picture-in-picture) ----------

    def toggle_pip_mode(self):
        win = self.win
        if win._player_fullscreen:
            # No tiene sentido combinar los dos modos a la vez; salir de
            # pantalla completa primero evita un estado confuso a medias.
            self.exit_player_fullscreen()
        if win._pip_mode:
            self.exit_pip_mode()
        else:
            self.enter_pip_mode()

    def enter_pip_mode(self):
        win = self.win
        win._pip_mode = True
        win._geometria_antes_pip = win.geometry()
        win._was_maximized_before_pip = win._pseudo_maximizado

        win.nav_rail.setVisible(False)
        win.content_widget.setVisible(False)
        win.content_widget.setMinimumWidth(0)
        win.library_sidebar.setVisible(False)
        win.statusBar().setVisible(False)
        # El PiP funciona como mini reproductor: conserva transporte y mute,
        # pero esconde acciones secundarias para no saturar la ventana.
        win._pip_compact_visibility = {
            widget: widget.isVisible() for widget in (
                win.fav_btn, win.cast_btn, win.record_btn, win.more_btn, win.volume_slider,
            )
        }
        for widget in win._pip_compact_visibility:
            widget.setVisible(False)
        win.now_playing_bar.setFixedHeight(96)
        # setMinimumSize(1000, 580) del arranque impediría encoger la
        # ventana a un tamaño de ventana flotante — se relaja mientras
        # dure el modo PiP y se restaura al salir.
        win.setMinimumSize(320, 240)

        win.pip_btn.setIcon(app_icons.icon_pip(
            accent_shades(win.settings.get("accent_color", palette.ACCENT))["lighter"]
        ))
        win.pip_btn.setToolTip("Salir de ventana flotante")

        win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        win.resize(460, 340)
        pantalla = (win.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        win.move(pantalla.right() - 480, pantalla.bottom() - 360)
        win.show()  # obligatorio tras cambiar setWindowFlag en una ventana visible

    def exit_pip_mode(self):
        win = self.win
        win._pip_mode = False

        win.nav_rail.setVisible(True)
        win.content_widget.setVisible(True)
        win.content_widget.setMinimumWidth(420)
        win.library_sidebar.setVisible(win.library_toggle_btn.isChecked())
        win.statusBar().setVisible(True)
        for widget, was_visible in getattr(win, "_pip_compact_visibility", {}).items():
            widget.setVisible(was_visible)
        win._pip_compact_visibility = {}
        win.now_playing_bar.setFixedHeight(118)
        # Debe coincidir con el mínimo fijado en MainWindow.__init__ -- ver
        # el comentario ahí sobre por qué 900 y no 1000.
        win.setMinimumSize(900, 580)

        win.pip_btn.setIcon(app_icons.icon_pip(palette.TEXT_PRIMARY))
        win.pip_btn.setToolTip("Ventana flotante")

        win.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        win.show()
        if win._geometria_antes_pip is not None:
            win.setGeometry(win._geometria_antes_pip)
        if win._was_maximized_before_pip:
            win._pseudo_maximizado = False
            self.maximizar()

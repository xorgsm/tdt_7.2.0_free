"""
Controlador de reproducción de TDT & Radio VIP.

Extraído de ui/main_window.py (antes una única clase de más de 2.000 líneas
que mezclaba construcción de interfaz, reproducción, grabación, temporizador
de apagado, navegación de listas, favoritos, historial, Chromecast y EPG).
Este módulo agrupa todo lo relacionado con "qué se está reproduciendo ahora
y cómo se controla": arrancar/parar, saltar de canal automáticamente si uno
falla, silenciar, grabar y el temporizador de apagado.

El estado real (self.win.current_type, self.win.player, self.win.recorder,
los widgets de la barra "reproduciendo ahora"...) sigue viviendo en
MainWindow, porque se lee y escribe desde muchas otras zonas de la ventana
(listas, favoritos, Chromecast, EPG) que no tiene sentido mover aquí solo
por esto — moverlo habría obligado a reescribir esos otros sitios sin
poder probar el resultado en una GUI real. Este controlador recibe la
ventana en el constructor ('window', guardada como self.win) y opera sobre
sus widgets y su estado: es una extracción de COMPORTAMIENTO, no de
estado. Sirve igual al propósito de reducir el tamaño de MainWindow — esta
lógica ya no vive mezclada con la construcción de la interfaz, la carga de
canales o el resto de secciones, y se puede leer y razonar sobre ella de
forma aislada.

Coder By X@R
"""
import logging

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QListWidget, QListWidgetItem, QMenu, QMessageBox,
)

from core import channels as tv_channels
from core import config as cfg
from core import epg as epg_module
from core import favorites as fav_store
from core import history as hist_store
from core import radio as radio_stations
from core import recorder as rec_module
from core import recording_schedule
from ui import icons as app_icons
from ui import palette
from ui.toast import show_toast
from ui.widgets import ROLE_DATA, dominant_color


logger = logging.getLogger(__name__)


class PlaybackController:
    """Reproducción, grabación y temporizador de apagado de MainWindow."""

    MAX_AUTO_SKIP = 6
    AUTO_SKIP_DELAY_MS = 2200
    # A partir de este número de fallos SEGUIDOS del mismo canal/emisora
    # (no total histórico, ver core.channels.record_channel_failure), se
    # ofrece ocultarlo -- ver _maybe_offer_autohide().
    AUTO_HIDE_THRESHOLD = 3

    def __init__(self, window):
        self.win = window

    # ---------- Reproducción ----------

    def play(self, item_type: str, name: str, url: str, tvg_id: str = "", logo: str = ""):
        win = self.win
        if win.recorder.is_recording:
            self.toggle_recording()

        win._playback_token += 1
        win.player.stop()
        win.equalizer.stop()
        win._playback_failed = False
        win.retry_btn.setVisible(False)
        win.now_subtitle.setStyleSheet("")

        if item_type == "tv":
            win.player_stack.setCurrentWidget(win.player)
            win.player.play(url)
            win.player.set_volume(win.volume_slider.value())
            # VLCPlayer recrea su media_player en cada play() (ver
            # _recrear_media_player en player/vlc_player.py), así que la
            # pista de vídeo vuelve a activarse por defecto en cada canal
            # nuevo -- hay que reafirmar el modo "solo audio" aquí si
            # estaba activo, no solo cuando el usuario lo alterna a mano.
            self._apply_audio_only_state()
        else:
            win.player_stack.setCurrentWidget(win.equalizer)
            win.player.play(url)
            win.player.set_volume(win.volume_slider.value())
            win.equalizer.set_intensity(0.0 if win.mute_btn.isChecked() else win.volume_slider.value() / 100)
            win.equalizer.start()

        win.current_type = item_type
        win.current_name = name
        win.current_url = url
        win.current_tvg_id = tvg_id
        win.current_logo = logo
        win.set_live_badge_visible(True)

        icon = "TV" if item_type == "tv" else "FM"
        win.now_title.setText(f"{icon} · {name}")
        win.now_subtitle.setText("TV en directo" if item_type == "tv" else "Radio online")
        # Borde de color en el logo de "reproduciendo ahora" según el tipo
        # de contenido -- mismo azul/naranja que ya usan TV/Radio en el
        # riel y las tarjetas, para que se note de un vistazo qué se está
        # escuchando sin tener que leer el subtítulo.
        tipo_accent = palette.ACCENT_INFO if item_type == "tv" else palette.ACCENT_CATEGORY_ORANGE
        win.now_logo.setStyleSheet(
            f"background-color: {palette.BG_PANEL_ALT}; border-radius: 10px; "
            f"border: 2px solid {tipo_accent};"
        )
        # El logo tarda en llegar (descarga/caché en segundo plano, ver
        # LogoLoader) -- en cuanto esté, update_now_logo() intenta afinar
        # este mismo borde con un color sacado del propio logo (ver más
        # abajo). Hasta entonces, o si el logo no da un color válido, se
        # queda el azul/naranja fijo de arriba.
        self.update_now_logo(logo, tipo_accent)
        win.play_btn.setText("⏸")
        self._pulse_now_playing()

        win.fav_btn.setChecked(fav_store.is_favorite(win.favorites, item_type, name))
        win.fav_btn.setText("★" if win.fav_btn.isChecked() else "☆")

        win.history = hist_store.add_entry(item_type, name, url)
        win.lists.refresh_history_tab()
        win.lists.mark_playing_everywhere()
        win._refresh_home_now_playing()

        self.update_epg_display()

        # Si tras el margen de auto-salto esto sigue siendo lo que suena y
        # no ha fallado, se da por buena la reproducción y se resetea el
        # contador de fallos consecutivos de este canal/emisora (ver
        # on_player_error/_maybe_offer_autohide). El token evita marcar
        # como "ok" algo de lo que ya se cambió mientras tanto.
        token = win._playback_token
        QTimer.singleShot(self.AUTO_SKIP_DELAY_MS, lambda: self._confirm_playback_ok(item_type, name, token))

    def _confirm_playback_ok(self, item_type: str, name: str, token: int):
        win = self.win
        if token != win._playback_token or win._playback_failed:
            return
        store = tv_channels if item_type == "tv" else radio_stations
        store.reset_channel_failures(name)

    def update_now_logo(self, url: str, tipo_accent: str):
        """
        tipo_accent: color de reserva (azul TV / naranja radio) ya puesto
        por play() antes de llamar aquí -- si el logo no tiene un color
        de acento válido (dominant_color() devuelve None: logo en blanco
        y negro, sin logo, etc.) se deja tal cual, no hay nada más que
        hacer.
        """
        win = self.win
        win.now_logo.clear()
        if not url:
            return

        # Token capturado ANTES de la carga asíncrona del logo: si el
        # usuario cambia de canal mientras se descarga/lee de caché, este
        # callback no debe teñir el logo del canal NUEVO con el color del
        # viejo cuando por fin llegue.
        token = win._playback_token

        def _on_ready(pixmap):
            win.now_logo.setPixmap(pixmap)
            if token != win._playback_token:
                return
            color = dominant_color(pixmap)
            if color is not None:
                win.now_logo.setStyleSheet(
                    f"background-color: {palette.BG_PANEL_ALT}; border-radius: 10px; "
                    f"border: 2px solid {color.name()};"
                )

        win.logo_loader.load(url, _on_ready, size=44)

    def _pulse_now_playing(self):
        """
        Pequeño fundido de entrada en el nombre/logo de "reproduciendo
        ahora" al cambiar de canal: sin esto, el texto cambiaba de golpe y
        con canales parecidos (nombre similar, mismo logo mientras carga)
        no siempre se notaba a simple vista que había arrancado algo nuevo.
        """
        win = self.win
        effect = QGraphicsOpacityEffect(win.now_title)
        win.now_title.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", win.now_title)
        anim.setDuration(260)
        anim.setStartValue(0.25)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: win.now_title.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        win._now_playing_anim = anim

    def toggle_play(self):
        win = self.win
        if win.current_url is None:
            QMessageBox.information(
                win, "Nada seleccionado",
                "Elige primero un canal de TV o una emisora de radio en la lista."
            )
            return
        win.player.pause_toggle()
        playing = win.player.is_playing()
        win.play_btn.setText("⏸" if playing else "▶")
        win._taskbar.update_play_state(playing)
        if win.current_type == "radio":
            win.equalizer.start() if playing else win.equalizer.stop()
        win._refresh_home_now_playing()

    def on_player_error(self, message: str):
        win = self.win
        win.set_live_badge_visible(False)
        win._playback_failed = True
        win.equalizer.stop()
        win.play_btn.setText("▶")
        win.retry_btn.setVisible(True)
        win.now_subtitle.setText(f"⚠ {message}")
        win.now_subtitle.setStyleSheet(f"color: {palette.DANGER};")
        name = win.current_name or "el canal seleccionado"
        win.lists.mark_playing_everywhere()

        if win.current_type and win.current_name:
            store = tv_channels if win.current_type == "tv" else radio_stations
            fallos = store.record_channel_failure(win.current_name)
            self._maybe_offer_autohide(win.current_type, win.current_name, fallos)

        if win._active_list is not None and win._auto_skip_count < self.MAX_AUTO_SKIP:
            win._auto_skip_count += 1
            token = win._playback_token
            seconds = self.AUTO_SKIP_DELAY_MS / 1000
            win.statusBar().showMessage(
                f"«{name}» no responde. Probando el siguiente en {seconds:.0f}s…", self.AUTO_SKIP_DELAY_MS
            )
            QTimer.singleShot(self.AUTO_SKIP_DELAY_MS, lambda: self.auto_skip_next(token))
        else:
            win.statusBar().showMessage(
                f"No se pudo conectar con «{name}». Puede que el servidor esté caído.", 8000
            )
            win._auto_skip_count = 0

    def _maybe_offer_autohide(self, item_type: str, name: str, fallos: int):
        """
        A partir de AUTO_HIDE_THRESHOLD fallos SEGUIDOS del mismo
        canal/emisora, se ofrece ocultarlo de la lista pública con un
        aviso no bloqueante (ver ui/toast.py) en vez de un
        QMessageBox.question() modal -- esto se dispara en pleno
        auto-salto (ver on_player_error), y un diálogo modal ahí
        interrumpiría esa secuencia en vez de dejarla seguir de fondo
        mientras el usuario decide con calma.

        Solo se avisa la primera vez que se cruza el umbral (== en vez de
        >=): si el usuario descarta el aviso sin actuar, repetirlo en cada
        fallo posterior del mismo canal sería machacón.
        """
        if fallos != self.AUTO_HIDE_THRESHOLD:
            return
        win = self.win
        etiqueta = "Este canal" if item_type == "tv" else "Esta emisora"
        show_toast(
            win,
            f"«{name}» lleva {fallos} fallos seguidos. {etiqueta} podría estar caído.",
            undo_text="Ocultar",
            on_undo=lambda: win.library.hide_entries(item_type, [name]),
        )

    def on_player_end_reached(self):
        win = self.win
        if win._playback_failed:
            return
        # Si hay algo en la cola "Reproduciendo a continuación", se pasa a
        # ello automáticamente en vez de quedarse parado — igual que hace
        # Spotify al terminar una pista con cola pendiente.
        if win.queue.has_items():
            win.queue.play_next()
            return
        win.play_btn.setText("▶")
        win.set_live_badge_visible(False)
        win.equalizer.stop()
        win.statusBar().showMessage("La emisión se ha detenido.", 5000)
        win.lists.mark_playing_everywhere()

    def retry_playback(self):
        win = self.win
        if not win.current_url:
            return
        self.play(win.current_type, win.current_name, win.current_url, win.current_tvg_id, win.current_logo)

    def stop_playback(self):
        win = self.win
        if win.recorder.is_recording:
            self.toggle_recording()
        win.player.stop()
        win.equalizer.stop()
        win.play_btn.setText("▶")
        win.set_live_badge_visible(False)
        win.now_title.setText("Nada en reproducción")
        win.now_subtitle.setText("Elige un canal o una emisora")
        win.now_subtitle.setStyleSheet("")
        win.retry_btn.setVisible(False)
        win._playback_failed = False
        win._playback_token += 1
        win._active_list = None
        win._auto_skip_count = 0
        win.now_logo.clear()
        win.now_logo.setStyleSheet(f"background-color: {palette.BG_PANEL_ALT}; border-radius: 10px;")
        win.current_type = None
        win.current_name = None
        win.current_url = None
        win.lists.mark_playing_everywhere()
        win._refresh_home_now_playing()

    def on_volume_changed(self, value: int):
        win = self.win
        win.player.set_volume(value)
        win.settings["volume"] = value
        if not cfg.save_settings(win.settings):
            logger.warning("No se pudieron guardar los ajustes de reproducción")
        if win.current_type == "radio" and not win.mute_btn.isChecked():
            win.equalizer.set_intensity(value / 100)

    def toggle_mute(self):
        win = self.win
        muted = win.mute_btn.isChecked()
        win.player.set_muted(muted)
        # "muted" pinta el icono con palette.BG_ROOT, igual que
        # #muteButton[uiVariant="info"]:checked en ui/style.py sobre el
        # fondo palette.ACCENT_INFO -- mismo patrón que cast_btn/sleep_btn
        # en main_window.py.
        win.mute_btn.setIcon(app_icons.icon_speaker(palette.BG_ROOT if muted else palette.ACCENT_INFO, muted=muted))
        win._taskbar.update_mute_state(muted)
        if win.current_type == "radio":
            win.equalizer.set_intensity(0.0 if muted else win.volume_slider.value() / 100)

    def toggle_audio_only_tv(self):
        """
        Alterna el modo "solo audio" para canales de TV: desactiva la
        pista de vídeo del stream (ahorra CPU/batería, sobre todo en
        portátiles, cuando solo se quiere escuchar) y muestra el mismo
        ecualizador animado que ya se usa para radio en vez de un vídeo
        congelado o en negro. Es una preferencia persistente (se guarda en
        settings.json), no un estado de "esta reproducción concreta": se
        mantiene activa al cambiar de canal de TV -- ver la llamada a
        _apply_audio_only_state() en play().
        """
        win = self.win
        win._audio_only_tv = not win._audio_only_tv
        win.settings["audio_only_tv"] = win._audio_only_tv
        if not cfg.save_settings(win.settings):
            logger.warning("No se pudieron guardar los ajustes de reproducción")
        if win.current_type == "tv":
            self._apply_audio_only_state()
        estado = "activado" if win._audio_only_tv else "desactivado"
        win.statusBar().showMessage(f"Modo solo audio (TV) {estado}.", 5000)

    def _apply_audio_only_state(self):
        """
        Aplica (o quita) el modo "solo audio" al canal de TV en curso,
        según win._audio_only_tv -- ver toggle_audio_only_tv(). Solo debe
        llamarse cuando se sabe que hay un canal de TV activo (desde la
        rama "tv" de play(), o desde el propio toggle ya comprobado allí).
        """
        win = self.win
        if win._audio_only_tv:
            win.player.set_video_enabled(False)
            win.player_stack.setCurrentWidget(win.equalizer)
            win.equalizer.set_intensity(0.0 if win.mute_btn.isChecked() else win.volume_slider.value() / 100)
            win.equalizer.start()
        else:
            win.player.set_video_enabled(True)
            win.player_stack.setCurrentWidget(win.player)
            win.equalizer.stop()

    # ---------- Grabación ----------

    def toggle_recording(self):
        win = self.win
        if not win.recorder.is_recording:
            if not win.current_url:
                QMessageBox.information(
                    win, "Nada en reproducción",
                    "Selecciona y reproduce un canal o emisora antes de grabar."
                )
                win.record_btn.setChecked(False)
                return
            if not rec_module.Recorder.ffmpeg_available():
                QMessageBox.warning(
                    win, "ffmpeg no encontrado",
                    "No se encontró ffmpeg en el PATH del sistema. Instálalo para poder grabar streams."
                )
                win.record_btn.setChecked(False)
                return
            try:
                output_file = win.recorder.start(
                    win.current_url, win.current_name, kind=win.current_type or "tv"
                )
                win.record_btn.setChecked(True)
                win.record_btn.setGraphicsEffect(win._make_glow(QColor(palette.DANGER), blur=24, alpha=170))
                win.statusBar().showMessage(f"Grabando en: {output_file}")
                # ffmpeg puede arrancar el proceso sin problema y aun así no
                # llegar a grabar nada (URL que rechaza la conexión,
                # cabeceras que no acepta el servidor...) -- antes eso no se
                # detectaba nunca, y la app seguía diciendo "Grabando en..."
                # con un archivo que no se llegaba a escribir. Este chequeo
                # tardío (no bloqueante: el margen de espera vive en el
                # QTimer, no dentro de recorder.start()) lo detecta y avisa.
                QTimer.singleShot(
                    rec_module.STARTUP_GRACE_MS,
                    lambda f=output_file: self._check_recording_alive(f),
                )
            except RuntimeError as exc:
                QMessageBox.warning(win, "No se pudo grabar", str(exc))
                win.record_btn.setChecked(False)
        else:
            # on_wait=QApplication.processEvents: parar la grabación puede
            # tardar unos segundos (ffmpeg cerrando el archivo con
            # limpieza) -- sin esto, esa espera bloqueaba el hilo de la
            # interfaz entero y Windows llegaba a marcar la ventana como
            # "no responde" si tardaba lo bastante.
            finished_file, ok = win.recorder.stop(on_wait=QApplication.processEvents)
            win.record_btn.setChecked(False)
            win.record_btn.setGraphicsEffect(None)
            # Si lo que se acaba de parar a mano era en realidad una
            # grabación programada desde la EPG (ver
            # ui.tray_controller.TrayReminderController.check_scheduled_recordings),
            # hay que limpiar también su entrada en core.recording_schedule -- si no,
            # check_stops_due() la encontraría más tarde todavía marcada
            # "recording" e intentaría parar un self.recorder que ya
            # estaría libre para entonces (inofensivo, pero deja la
            # entrada colgada hasta esa hora en vez de irse ya).
            if win._scheduled_recording_active is not None:
                rec = win._scheduled_recording_active
                recording_schedule.mark_done(rec.tvg_id, rec.title, rec.start)
                win._scheduled_recording_active = None
            if ok:
                win.statusBar().showMessage(f"Grabación guardada: {finished_file}", 8000)
            elif finished_file:
                QMessageBox.warning(
                    win, "Grabación vacía",
                    f"Se detuvo la grabación, pero el archivo no tiene contenido "
                    f"real (probablemente ffmpeg no llegó a conectar con el "
                    f"stream):\n\n{finished_file}"
                )

    def _check_recording_alive(self, expected_file):
        """
        Llamado desde el QTimer que arranca toggle_recording() al iniciar
        una grabación. Si mientras tanto el usuario ya paró la grabación a
        mano, o empezó una distinta, esta comprobación tardía ya no aplica
        y no hace nada.
        """
        win = self.win
        if not win.recorder.is_recording or win.recorder.current_file != expected_file:
            return
        motivo = win.recorder.check_early_failure()
        if motivo is not None:
            win.record_btn.setChecked(False)
            win.record_btn.setGraphicsEffect(None)
            QMessageBox.warning(win, "La grabación no arrancó", motivo)

    # ---------- Navegación entre canales de la lista activa ----------

    def auto_skip_next(self, token: int):
        win = self.win
        if token != win._playback_token or win._active_list is None:
            return
        lst = win._active_list
        row = win._active_row + 1
        while row < lst.count() and lst.item(row).isHidden():
            row += 1
        if row >= lst.count():
            win.statusBar().showMessage("No quedan más canales que probar automáticamente en esta lista.", 6000)
            win._auto_skip_count = 0
            return
        win.statusBar().showMessage("Canal no disponible, probando el siguiente…", self.AUTO_SKIP_DELAY_MS)
        self.activate_item(lst.item(row), lst, is_auto=True)

    def on_item_activated(self, item: QListWidgetItem, list_widget: QListWidget):
        self.activate_item(item, list_widget, is_auto=False)

    def activate_item(self, item: QListWidgetItem, list_widget: QListWidget, is_auto: bool = False):
        win = self.win
        data = item.data(ROLE_DATA)
        if not data or not data.get("url"):
            if not is_auto:
                QMessageBox.warning(win, "Sin enlace", "Este elemento no tiene un enlace de reproducción válido.")
            return
        win._active_list = list_widget
        win._active_row = list_widget.row(item)
        if not is_auto:
            win._auto_skip_count = 0
        self.play(data["type"], data["name"], data["url"], data.get("tvg_id", ""), data.get("logo", ""))

    def play_prev(self):
        win = self.win
        if win._active_list is None:
            return
        row = win._active_row - 1
        while row >= 0 and win._active_list.item(row).isHidden():
            row -= 1
        if row >= 0:
            self.activate_item(win._active_list.item(row), win._active_list)

    def play_next(self):
        win = self.win
        # El botón "siguiente" (y la tecla multimedia equivalente) mira
        # primero la cola manual antes de caer al siguiente canal de la
        # lista activa: si el usuario ha puesto algo en cola a propósito,
        # "siguiente" debe respetar esa intención antes que el orden de la
        # lista.
        if win.queue.has_items():
            win.queue.play_next()
            return
        if win._active_list is None:
            return
        row = win._active_row + 1
        while row < win._active_list.count() and win._active_list.item(row).isHidden():
            row += 1
        if row < win._active_list.count():
            self.activate_item(win._active_list.item(row), win._active_list)

    # ---------- Temporizador de apagado ----------

    def on_sleep_btn_clicked(self):
        """Muestra un menú contextual para elegir el tiempo de apagado."""
        win = self.win
        if win._sleep_timer.isActive():
            self.cancelar_sleep()
            return
        menu = QMenu(win)
        acento = win.settings.get("accent_color", palette.ACCENT)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {palette.BG_PANEL}; color: {palette.TEXT_PRIMARY}; "
            f"border: 1px solid {palette.BORDER}; }}"
            f"QMenu::item:selected {{ background-color: {acento}; color: {palette.BG_ROOT}; }}"
        )
        menu.addAction("60 minutos", lambda: self.iniciar_sleep(60))
        menu.addAction("90 minutos", lambda: self.iniciar_sleep(90))
        menu.addAction("120 minutos", lambda: self.iniciar_sleep(120))
        menu.addSeparator()
        menu.addAction("Cancelar temporizador", self.cancelar_sleep)
        # Ancla a more_btn: sleep_btn ya no vive en ningún layout visible
        # (ver ui/main_window.py _build_now_playing_bar) y su posición en
        # pantalla no sería fiable para mapToGlobal.
        menu.exec(win.more_btn.mapToGlobal(win.more_btn.rect().bottomLeft()))
        # Si el usuario cierra el menú sin elegir nada, desmarcar el botón.
        if not win._sleep_timer.isActive():
            win.sleep_btn.setChecked(False)

    def iniciar_sleep(self, minutos: int):
        win = self.win
        win._sleep_minutes_left = minutos
        win._sleep_timer.start(minutos * 60 * 1000)
        win._sleep_countdown.start()
        win.sleep_btn.setChecked(True)
        win.sleep_btn.setToolTip(f"Apagado en {minutos} min — clic para cancelar")
        win.statusBar().showMessage(
            f"⏾  Temporizador activo: apagado en {minutos} minutos.", 6000
        )

    def cancelar_sleep(self):
        win = self.win
        win._sleep_timer.stop()
        win._sleep_countdown.stop()
        win._sleep_minutes_left = 0
        win.sleep_btn.setChecked(False)
        win.sleep_btn.setToolTip("Temporizador de apagado")
        win.statusBar().showMessage("Temporizador cancelado.", 4000)

    def update_sleep_tooltip(self):
        win = self.win
        win._sleep_minutes_left = max(0, win._sleep_minutes_left - 1)
        if win._sleep_minutes_left > 0:
            win.sleep_btn.setToolTip(
                f"Apagado en {win._sleep_minutes_left} min — clic para cancelar"
            )

    def on_sleep_timeout(self):
        win = self.win
        win._sleep_countdown.stop()
        win._sleep_minutes_left = 0
        win.sleep_btn.setChecked(False)
        win.sleep_btn.setToolTip("Temporizador de apagado")
        win.player.stop()
        win.equalizer.stop()
        win.play_btn.setText("▶")
        win.statusBar().showMessage("Temporizador: reproducción detenida.", 8000)

    # ---------- EPG ----------

    def update_epg_display(self):
        win = self.win
        if win.current_type != "tv" or not win.current_tvg_id or not win.epg_guide:
            return
        current, upcoming = epg_module.get_now_next(win.epg_guide, win.current_tvg_id)
        if current:
            win.now_subtitle.setText(f"Ahora: {current.title}")
        elif upcoming:
            win.now_subtitle.setText(f"A continuación: {upcoming.title}")

    # ---------- Favoritos del elemento en reproducción ----------

    def toggle_favorite_current(self):
        win = self.win
        if not win.current_name:
            win.fav_btn.setChecked(False)
            return
        win.favorites = fav_store.toggle_favorite(
            win.current_type, win.current_name, win.current_url or "", win.current_logo or ""
        )
        win.fav_btn.setText("★" if win.fav_btn.isChecked() else "☆")
        win.lists.refresh_favorites_tab()
        win.lists.mark_favorites_everywhere()

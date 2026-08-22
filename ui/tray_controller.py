"""
Controlador de la bandeja del sistema de TDT & Radio VIP: icono de
bandeja, avisos de la guía EPG marcados por el usuario, y arranque/parada
de grabaciones programadas desde la EPG.

Extraído de ui/main_window.py por el mismo motivo que el resto de
controladores (ver ui/playback_controller.py).

Coder By X@R
"""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from core import epg as epg_module
from core import epg_reminders
from core import recorder as rec_module
from core import recording_schedule
from core import recurring_recordings
from ui import palette


class TrayReminderController:
    """Bandeja del sistema, avisos EPG y grabaciones programadas."""

    def __init__(self, window):
        self.win = window

    def setup(self):
        """
        Icono de bandeja del sistema para poder avisar de un programa
        marcado en la parrilla EPG aunque la ventana esté minimizada.
        Se comprueba cada 30s si algún aviso pendiente ya toca dispararse,
        y también si hay que arrancar o parar alguna grabación programada
        -- mismo temporizador para ambas cosas, no hace falta uno
        independiente por lo poco que cuesta cada comprobación.
        """
        win = self.win
        win._tray_icon = QSystemTrayIcon(win.windowIcon(), win)
        win._tray_icon.setToolTip("TDT & Radio VIP")
        win._tray_icon.messageClicked.connect(self.on_tray_message_clicked)
        win._tray_icon.show()

        win._pending_reminder_tune = None
        win._reminder_timer = QTimer(win)
        win._reminder_timer.setInterval(30_000)
        win._reminder_timer.timeout.connect(self.check_epg_reminders)
        win._reminder_timer.timeout.connect(self.check_scheduled_recordings)
        win._reminder_timer.start()
        self.check_epg_reminders()  # una comprobación inmediata, no solo tras 30s
        self.check_scheduled_recordings()

    def check_epg_reminders(self):
        win = self.win
        if getattr(win, "_is_closing", False):
            return
        disparados = epg_reminders.check_due(epg_module.parse_xmltv_time)
        for r in disparados:
            win._tray_icon.showMessage(
                "Empieza ahora",
                f"{r.title} — {r.channel_name}",
                QSystemTrayIcon.Information,
                8000,
            )
            win._pending_reminder_tune = r.tvg_id

    def check_scheduled_recordings(self):
        """
        Arranca/para grabaciones programadas desde la guía EPG (ver
        ui/epg_dialog.py, "Grabar automáticamente"). core.recording_schedule
        solo lleva la contabilidad de qué toca ahora mismo -- este método es
        el único sitio que de verdad toca win.recorder y la interfaz.
        """
        win = self.win
        if getattr(win, "_is_closing", False):
            return
        # Antes de comprobar qué toca arrancar/parar, se sincronizan las
        # reglas recurrentes (ver core/recurring_recordings.py): si alguna
        # toca hoy y no se había insertado ya, se le crea aquí su
        # ScheduledRecording concreta de hoy -- a partir de ahí sigue el
        # mismo camino de siempre, como si viniera de la EPG.
        recurring_recordings.sync_into_schedule()

        a_parar = recording_schedule.check_stops_due(epg_module.parse_xmltv_time)
        for r in a_parar:
            es_la_activa = (
                win._scheduled_recording_active is not None
                and win._scheduled_recording_active.tvg_id == r.tvg_id
                and win._scheduled_recording_active.title == r.title
                and win._scheduled_recording_active.start == r.start
            )
            if es_la_activa and win.recorder.is_recording:
                finished_file, ok = win.recorder.stop(on_wait=QApplication.processEvents)
                # Recorder.stop() bombea eventos para que la UI siga respondiendo
                # mientras termina ffmpeg. Ese pump puede entregar closeEvent(),
                # que deja la ventana en cierre mientras este callback ya estaba
                # en curso. La parada ya se completó: limpia su programación,
                # pero no vuelvas a tocar la interfaz ni intentes otro arranque.
                if getattr(win, "_is_closing", False):
                    win._scheduled_recording_active = None
                    recording_schedule.mark_done(r.tvg_id, r.title, r.start)
                    return
                win.record_btn.setChecked(False)
                win.record_btn.setGraphicsEffect(None)
                win._scheduled_recording_active = None
                mensaje = f"«{r.title}» guardado." if ok else f"«{r.title}»: la grabación quedó vacía."
                win._tray_icon.showMessage(
                    "Grabación programada terminada", mensaje, QSystemTrayIcon.Information, 8000
                )
                if finished_file:
                    win.statusBar().showMessage(f"Grabación programada guardada: {finished_file}", 8000)
            # Si no es la que está grabando ahora mismo (se paró a mano
            # antes, o nunca llegó a arrancar de verdad), no hay nada que
            # detener en win.recorder -- solo se limpia la programación.
            recording_schedule.mark_done(r.tvg_id, r.title, r.start)

        # Una parada anterior puede haber bombeado closeEvent(); no consultes
        # ni inicies grabaciones nuevas una vez que comenzó el cierre.
        if getattr(win, "_is_closing", False):
            return
        a_arrancar = recording_schedule.check_starts_due(epg_module.parse_xmltv_time)
        for r in a_arrancar:
            if getattr(win, "_is_closing", False):
                return
            if win.recorder.is_recording:
                # Ya hay algo grabando (manual, u otra programada que se
                # solapa) -- Recorder solo soporta una grabación a la vez.
                # Se deja constancia del fallo en vez de intentarlo y
                # reventar con RuntimeError.
                recording_schedule.mark_error(r.tvg_id, r.title, r.start)
                win._tray_icon.showMessage(
                    "Grabación programada no iniciada",
                    f"«{r.title}» — ya había otra grabación en curso.",
                    QSystemTrayIcon.Warning, 8000,
                )
                continue
            if not rec_module.Recorder.ffmpeg_available():
                recording_schedule.mark_error(r.tvg_id, r.title, r.start)
                continue
            try:
                if getattr(win, "_is_closing", False):
                    return
                output_file = win.recorder.start(r.channel_url, r.channel_name)
            except RuntimeError:
                recording_schedule.mark_error(r.tvg_id, r.title, r.start)
                win._tray_icon.showMessage(
                    "Grabación programada no iniciada",
                    f"«{r.title}» ({r.channel_name}) — no se pudo arrancar ffmpeg.",
                    QSystemTrayIcon.Warning, 8000,
                )
                continue
            win._scheduled_recording_active = r
            win.record_btn.setChecked(True)
            win.record_btn.setGraphicsEffect(win._make_glow(QColor(palette.DANGER), blur=24, alpha=170))
            win.statusBar().showMessage(f"Grabación programada iniciada: {output_file}", 8000)
            win._tray_icon.showMessage(
                "Grabación programada iniciada",
                f"{r.title} — {r.channel_name}",
                QSystemTrayIcon.Information, 6000,
            )
            QTimer.singleShot(
                rec_module.STARTUP_GRACE_MS,
                lambda f=output_file, rec=r: self.check_scheduled_recording_alive(f, rec),
            )

    def check_scheduled_recording_alive(self, expected_file, rec: "recording_schedule.ScheduledRecording"):
        """Mismo chequeo tardío que PlaybackController._check_recording_alive
        (ver ese método para el porqué), aplicado a una grabación que
        arrancó sola desde la programación EPG en vez de por el botón de
        grabar."""
        win = self.win
        if not win.recorder.is_recording or win.recorder.current_file != expected_file:
            return
        motivo = win.recorder.check_early_failure()
        if motivo is not None:
            win.record_btn.setChecked(False)
            win.record_btn.setGraphicsEffect(None)
            win._scheduled_recording_active = None
            recording_schedule.mark_error(rec.tvg_id, rec.title, rec.start)
            win._tray_icon.showMessage(
                "La grabación programada no arrancó",
                f"{rec.title} — {rec.channel_name}",
                QSystemTrayIcon.Warning, 8000,
            )

    def on_tray_message_clicked(self):
        win = self.win
        if not win._pending_reminder_tune:
            return
        win.epg.tune_to_tvg_id(win._pending_reminder_tune)
        win._pending_reminder_tune = None
        win.showNormal()
        win.raise_()
        win.activateWindow()

    def notify(self, title: str, message: str, icon=QSystemTrayIcon.Information, timeout_ms: int = 6000):
        """
        Aviso de bandeja genérico y reutilizable (en Windows 10/11, Qt lo
        muestra como notificación nativa del Centro de actividades) --
        pensado para sitios de la app que quieran avisar de algo aunque la
        ventana esté minimizada, sin tener que reimplementar el icono de
        bandeja cada vez. Ver los avisos de grabación en
        ui/main_window.py para el primer uso.
        """
        win = self.win
        if getattr(win, "_tray_icon", None) is not None:
            win._tray_icon.showMessage(title, message, icon, timeout_ms)

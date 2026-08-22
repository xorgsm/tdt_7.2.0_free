"""
Reproductor de solo-audio, ligero, para previsualizar un MP3 y marcar
puntos de inicio/fin (ver ui/mp3_editor_panel.py).

No reutiliza VLCPlayer (player/vlc_player.py): ese widget está pensado para
vídeo con salida a una ventana (QFrame + handle nativo, gestión de vout...),
todo innecesario aquí -- este reproductor no pinta nada, solo decodifica
audio. Usa la misma libVLC ya localizada por core/bootstrap.py al arrancar
la app, así que no hace falta repetir esa configuración.

Coder By X@R
"""
from PySide6.QtCore import QObject, Qt, Signal

from core.logger import get_logger

log = get_logger(__name__)

try:
    import vlc
    VLC_IMPORT_ERROR = None
except Exception as _exc:  # ImportError, OSError al cargar libvlc.dll…
    vlc = None
    VLC_IMPORT_ERROR = str(_exc)


class AudioPreviewPlayer(QObject):
    """Reproductor de audio mínimo: cargar un archivo, reproducir/pausar,
    y leer/mover la posición de reproducción en milisegundos."""

    error_occurred = Signal(str)
    end_reached = Signal()

    _error_desde_vlc = Signal(str)
    _fin_desde_vlc = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instance = None
        self.media_player = None
        self._media_actual = None
        # Los callbacks de libVLC llegan desde su propio hilo -- en cola
        # explícitamente para no ejecutar nada de Qt fuera del hilo de la
        # interfaz (mismo motivo que en player/vlc_player.py).
        self._error_desde_vlc.connect(self.error_occurred, Qt.QueuedConnection)
        self._fin_desde_vlc.connect(self.end_reached, Qt.QueuedConnection)
        self._crear_instancia()

    def _crear_instancia(self):
        if vlc is None:
            return
        try:
            self.instance = vlc.Instance(["--quiet"])
            if self.instance is None:
                return
            self.media_player = self.instance.media_player_new()
            events = self.media_player.event_manager()
            events.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)
            events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_reached)
        except Exception:
            log.exception("No se pudo inicializar libVLC para la vista previa de audio")
            # Si el fallo llegó después de crear instance/media_player (p.ej.
            # event_attach), liberarlos antes de soltar la referencia -- si
            # no, quedan huérfanos en libVLC sin que nada vuelva a liberarlos.
            if self.media_player is not None:
                try:
                    self.media_player.release()
                except Exception:
                    pass
            if self.instance is not None:
                try:
                    self.instance.release()
                except Exception:
                    pass
            self.instance = None
            self.media_player = None

    def _on_vlc_error(self, _event):
        self._error_desde_vlc.emit("Error al reproducir el archivo de vista previa.")

    def _on_vlc_end_reached(self, _event):
        self._fin_desde_vlc.emit()

    @property
    def disponible(self) -> bool:
        return self.media_player is not None

    def load(self, path: str) -> bool:
        if not self.disponible:
            self.error_occurred.emit("No se pudo inicializar el motor de audio de VLC.")
            return False
        media = self.instance.media_new(path)
        self.media_player.set_media(media)
        if self._media_actual is not None:
            try:
                self._media_actual.release()
            except Exception:
                pass
        self._media_actual = media
        return True

    def play(self):
        if self.media_player is not None:
            self.media_player.play()

    def pause(self):
        if self.media_player is not None:
            self.media_player.set_pause(1)

    def stop(self):
        if self.media_player is not None:
            self.media_player.stop()

    def is_playing(self) -> bool:
        return self.media_player is not None and self.media_player.is_playing() == 1

    def get_time_ms(self) -> int:
        if self.media_player is None:
            return 0
        return max(0, self.media_player.get_time())

    def set_time_ms(self, ms: int):
        if self.media_player is not None:
            self.media_player.set_time(max(0, int(ms)))

    def get_length_ms(self) -> int:
        if self.media_player is None:
            return 0
        return max(0, self.media_player.get_length())

    def release(self):
        if self._media_actual is not None:
            try:
                self._media_actual.release()
            except Exception:
                pass
            self._media_actual = None
        if self.media_player is not None:
            try:
                self.media_player.stop()
                self.media_player.release()
            except Exception:
                pass
            self.media_player = None
        if self.instance is not None:
            try:
                self.instance.release()
            except Exception:
                pass
            self.instance = None

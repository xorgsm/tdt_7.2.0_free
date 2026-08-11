"""
Grabación de streams en curso mediante ffmpeg.

Usa el ffmpeg empaquetado con la aplicación si está disponible, y solo recurre
al del PATH del sistema como alternativa. Esto es lo que permite que la
grabación funcione en un PC donde ffmpeg no está instalado.
"""
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from core.config import get_ffmpeg_exe
from core.logger import get_logger

log = get_logger(__name__)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Fuente para la marca de agua. La app es solo para Windows y Arial está
# presente prácticamente en cualquier instalación, así que no hace falta
# empaquetar una fuente propia. Si por lo que sea no existe (Windows
# manipulado, fuente desinstalada...), se detecta en start() y se graba sin
# marca de agua en vez de romper la grabación entera por esto.
#
# Separada en carpeta + nombre de archivo (no en una única ruta) a
# propósito -- ver el porqué en el comentario de start() donde se usa
# _WATERMARK_FONT_DIR como cwd del proceso de ffmpeg. Resumen: la ruta
# completa con "C:\" rompe el parseo del filtro drawtext SIEMPRE, incluso
# ya escapada -- es un problema conocido de ffmpeg (fontfile hace su
# propio parseo interno estilo fontconfig, que también corta por ':',
# y una sola capa de escapado no basta para las dos a la vez). Sin
# ninguna ruta con ':' ni '\' dentro del filtro, el problema desaparece
# entero en vez de perseguir la forma exacta de escapar que le valga a
# cada versión de ffmpeg.
_WATERMARK_FONT_DIR = r"C:\Windows\Fonts"
_WATERMARK_FONT_NAME = "arial.ttf"
_WATERMARK_FONT = os.path.join(_WATERMARK_FONT_DIR, _WATERMARK_FONT_NAME)


def _escape_drawtext(text: str) -> str:
    """
    Escapa los caracteres que el propio filtro drawtext de ffmpeg interpreta
    como parte de su sintaxis (':', ''' y '\\'). Sin esto, un nombre de canal
    con dos puntos o un apóstrofe (poco frecuente, pero pasa) rompería el
    filtro entero y la grabación fallaría.
    """
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# Muchos orígenes de streams IPTV/TDT (sobre todo restreams comunitarios,
# como el que dio pie a este arreglo) filtran por cabeceras HTTP: aceptan
# el User-Agent que manda un reproductor "normal" pero rechazan el que
# manda ffmpeg por defecto ("Lavf/x.y.z", fácil de identificar como bot).
# VLC sí reproducía el mismo canal con normalidad -- de ahí que grabar
# fallara mientras que VER el canal funcionaba. Con un User-Agent de
# navegador normal, ffmpeg pasa ese filtro igual que lo pasaría VLC.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cuánto debe esperar quien llame a check_early_failure() (la UI, con un
# QTimer) antes de comprobar si ffmpeg sigue vivo. Si el servidor rechaza
# la conexión o la URL no responde, ffmpeg suele morir en el primer
# segundo o dos -- este margen es lo bastante corto para no hacer esperar
# al usuario, y lo bastante largo para no confundir un fallo real con el
# arranque normal (que también tarda un poco en conectar).
STARTUP_GRACE_MS = 2000

# Por debajo de esto, un .mp4 no es una grabación real (cabecera del
# contenedor sin apenas datos detrás) -- casi seguro que ffmpeg murió
# nada más empezar y lo que queda es un archivo vacío o casi vacío.
_MIN_VALID_SIZE_BYTES = 4096


class Recorder:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.process: Optional[subprocess.Popen] = None
        self.current_file: Optional[Path] = None
        self.current_log: Optional[Path] = None
        self._log_fh = None

    @staticmethod
    def ffmpeg_available() -> bool:
        return get_ffmpeg_exe() is not None

    def _log_tail(self, max_chars: int = 600) -> str:
        """Últimas líneas del log de ffmpeg, para mostrar en el aviso de error."""
        if not self.current_log or not self.current_log.exists():
            return ""
        try:
            texto = self.current_log.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        return texto[-max_chars:].strip()

    def start(self, stream_url: str, channel_name: str) -> Path:
        if self.process is not None:
            raise RuntimeError("Ya hay una grabación en curso.")

        ffmpeg = get_ffmpeg_exe()
        if ffmpeg is None:
            raise RuntimeError(
                "No se encontró ffmpeg, necesario para grabar."
            )

        safe_name = "".join(c for c in channel_name if c.isalnum() or c in " _-").strip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name or 'grabacion'}_{timestamp}.mp4"
        self.current_file = self.output_dir / filename
        self.current_log = self.current_file.with_suffix(".log")

        cmd = [
            ffmpeg, "-y",
            "-user_agent", _USER_AGENT,
            # Reintenta solo la conexión inicial/reconexiones de red — no
            # tapa un fallo real (URL caída, canal ya no existe), pero sí
            # los cortes de red pasajeros que son bastante frecuentes en
            # streams IPTV de larga duración.
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", stream_url,
        ]

        usar_marca_agua = os.path.exists(_WATERMARK_FONT)
        if usar_marca_agua:
            texto = _escape_drawtext(channel_name or "TDT & Radio VIP")
            # Esquina inferior derecha, semitransparente, con una caja detrás
            # para que se lea igual sobre fondos claros que oscuros.
            # fontfile lleva SOLO el nombre de archivo, sin ruta -- ver el
            # porqué en el comentario de _WATERMARK_FONT_DIR más arriba.
            # ffmpeg lo busca junto al cwd del proceso, que se fija más
            # abajo al lanzar Popen.
            drawtext = (
                f"drawtext=fontfile={_WATERMARK_FONT_NAME}:text='{texto}':"
                "fontsize=18:fontcolor=white@0.8:"
                "box=1:boxcolor=black@0.45:boxborderw=6:"
                "x=w-text_w-16:y=h-text_h-16"
            )
            # Con marca de agua ya no vale el stream copy de vídeo: hay que
            # re-codificar para "quemar" el texto en la imagen. El audio
            # sigue en copy, que es lo que de verdad pesa en CPU.
            cmd += [
                "-vf", drawtext,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy",
            ]
        else:
            # Sin la fuente no se puede quemar el texto; se graba igual, sin
            # marca de agua, en vez de dejar al usuario sin grabación.
            cmd += ["-c", "copy"]

        # No se fuerza aac_adtstoasc: ese filtro solo admite AAC y hace que
        # FFmpeg rechace canales perfectamente válidos con audio E-AC-3. El
        # muxer MP4 de las versiones empaquetadas maneja por sí mismo tanto
        # AAC procedente de HLS como E-AC-3.
        cmd += [str(self.current_file)]

        # stderr a un archivo (antes DEVNULL): si ffmpeg no consigue
        # conectar con el stream, moría sin dejar ningún rastro de por qué
        # -- la app seguía diciendo "Grabando en..." con un .mp4 que nunca
        # llegaba a escribirse. Con el log, el aviso de error puede
        # enseñar la causa real en vez de fallar en silencio.
        try:
            self._log_fh = open(self.current_log, "wb")
        except OSError:
            self._log_fh = None  # no poder loguear no debe impedir grabar

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._log_fh or subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
                # Con marca de agua, fontfile es solo un nombre de archivo
                # (ver más arriba) -- ffmpeg lo busca relativo al cwd del
                # proceso, así que hay que arrancarlo ya dentro de la
                # carpeta de fuentes. -i (la URL del stream) y la ruta de
                # salida van siempre en absoluto, así que cwd no les afecta.
                cwd=_WATERMARK_FONT_DIR if usar_marca_agua else None,
            )
        except OSError as exc:
            self.current_file = None
            if self._log_fh:
                self._log_fh.close()
                self._log_fh = None
            log.exception("No se pudo arrancar ffmpeg para grabar (canal/emisora en cmd: %s)", cmd)
            raise RuntimeError(f"No se pudo iniciar la grabación: {exc}") from exc

        return self.current_file

    def check_early_failure(self) -> Optional[str]:
        """
        Comprueba si ffmpeg ya ha muerto -- pensada para llamarse desde un
        QTimer un par de segundos después de start() (ver
        _STARTUP_GRACE_SECONDS), NUNCA desde dentro de start() mismo: un
        time.sleep() ahí bloquearía la interfaz entera justo al pulsar
        "grabar", que es peor que el problema que se intenta arreglar.

        Si el proceso ya murió, limpia el estado y devuelve un mensaje de
        error listo para mostrar. Si sigue vivo (lo normal), no toca nada
        y devuelve None.
        """
        if self.process is None or self.process.poll() is None:
            return None
        motivo = self._log_tail()
        self._reset_state()
        detalle = f"\n\nDetalle de ffmpeg:\n{motivo}" if motivo else ""
        return (
            "ffmpeg se cerró justo al arrancar; no se ha grabado nada "
            f"(¿la URL del stream no responde o el servidor la rechaza?).{detalle}"
        )

    def _reset_state(self):
        if self._log_fh:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None
        self.process = None
        self.current_file = None
        # current_log se conserva a propósito tras _reset_state (no se
        # pone a None aquí): es lo único que queda para poder enseñarle al
        # usuario dónde está el detalle del fallo después de que
        # start()/stop() ya hayan limpiado el resto del estado.

    def _wait_until(self, proceso, deadline: float, on_wait=None, poll_interval: float = 0.05):
        """
        Espera a que el proceso termine sin un único communicate()/wait()
        bloqueante largo -- eso es justo lo que antes hacía que la app
        entera se congelara (Windows la marcaba como "no responde") al
        cerrarla con una grabación en curso: un bloqueo de hasta 15
        segundos en el hilo de la interfaz sin que el bucle de eventos de
        Qt pudiera procesar nada mientras tanto. Sondeando en trocitos
        pequeños y dejando que quien llame "bombee" el bucle de eventos
        entre sondeo y sondeo (on_wait, normalmente
        QApplication.processEvents), la ventana sigue respondiendo aunque
        la espera real tarde lo mismo.
        """
        while proceso.poll() is None and time.monotonic() < deadline:
            if on_wait:
                on_wait()
            time.sleep(poll_interval)
        return proceso.poll() is not None

    def stop(self, on_wait=None) -> Tuple[Optional[Path], bool]:
        """
        Detiene la grabación pidiéndole a ffmpeg que cierre limpiamente ('q'),
        de forma que el MP4 quede con su índice bien escrito y sea reproducible.
        Si no responde, se fuerza el cierre, pero siempre se recoge el proceso:
        antes podía quedarse un ffmpeg huérfano escribiendo en segundo plano.

        on_wait: callback opcional invocado repetidamente mientras se
        espera (ver _wait_until) -- la UI le pasa QApplication.processEvents
        para no bloquearse durante la espera. Sin él, se comporta como una
        espera bloqueante normal (uso desde fuera de la interfaz, o tests).

        Devuelve (archivo, ok). ok=False si el archivo no llegó a escribirse
        con contenido real -- antes se daba la grabación por buena con solo
        haber arrancado el proceso, así que un fallo a mitad de grabación
        (stream cortado, servidor caído) se reportaba igualmente como
        "Grabación guardada" con un .mp4 vacío o corrupto detrás.
        """
        proceso = self.process
        archivo = self.current_file
        if proceso is None:
            return None, False

        try:
            if proceso.stdin:
                proceso.stdin.write(b"q")
                proceso.stdin.flush()
        except (OSError, ValueError):
            pass  # el proceso ya puede haber muerto por su cuenta

        try:
            if not self._wait_until(proceso, time.monotonic() + 5, on_wait):
                proceso.terminate()
                if not self._wait_until(proceso, time.monotonic() + 3, on_wait):
                    proceso.kill()
                    proceso.wait(timeout=5)
        except Exception:
            log.exception(
                "ffmpeg no respondió al cierre normal; forzando kill() (grabación: %s)",
                self.current_file,
            )
            try:
                proceso.kill()
                proceso.wait(timeout=5)
            except Exception:
                log.exception("kill() del proceso ffmpeg también falló")

        self._reset_state()

        ok = bool(archivo and archivo.exists() and archivo.stat().st_size >= _MIN_VALID_SIZE_BYTES)
        return archivo, ok

    @property
    def is_recording(self) -> bool:
        return self.process is not None

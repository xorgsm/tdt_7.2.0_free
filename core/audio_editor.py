"""
Unión de varios MP3 (con recorte opcional de cada uno) en un solo MP3,
con transición de fundido cruzado (crossfade) entre cada par consecutivo
para que no se note ni el corte ni un posible salto de volumen.

Todo en una sola llamada a ffmpeg: cada segmento entra como un input propio
(recortado con -ss/-t, seek de entrada), se normaliza en volumen y se
homogeneiza formato/sample rate (necesario para que acrossfade pueda
combinarlos), y se encadenan con el filtro acrossfade. Evita archivos
temporales intermedios por segmento.

Coder By X@R
"""
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QThread, Signal

from core.config import get_ffmpeg_exe
from core.logger import get_logger

log = get_logger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

MP3_BITRATE = "320k"
DEFAULT_FADE_SECONDS = 2.0
MIN_FADE_SECONDS = 1.0
MAX_FADE_SECONDS = 5.0

# Formato común al que se lleva cada segmento antes del crossfade -- sin
# esto, acrossfade falla en cuanto dos MP3 de origen tienen distinto sample
# rate o número de canales (habitual al mezclar archivos de fuentes
# distintas).
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
_AFORMAT = "aformat=sample_rates=44100:channel_layouts=stereo"


@dataclass(frozen=True)
class Segment:
    path: str
    start_ms: Optional[int] = None  # None = desde el principio
    end_ms: Optional[int] = None    # None = hasta el final


def _segment_input_args(segment: Segment) -> list:
    args = []
    if segment.start_ms:
        args += ["-ss", f"{segment.start_ms / 1000:.3f}"]
    if segment.end_ms is not None:
        inicio = segment.start_ms or 0
        duracion = max(0, segment.end_ms - inicio)
        args += ["-t", f"{duracion / 1000:.3f}"]
    args += ["-i", segment.path]
    return args


def build_join_command(
    segments: list, fade_seconds: float, output_path: str, ffmpeg: str
) -> list:
    """
    Construye el comando ffmpeg que une `segments` (lista de Segment, en el
    orden final deseado) en `output_path`, con `fade_seconds` de fundido
    cruzado entre cada par consecutivo. Con un solo segmento no hay nada que
    fundir: se recorta y re-codifica igualmente, para un comportamiento
    consistente (siempre MP3 320k de salida).
    """
    if not segments:
        raise ValueError("Hace falta al menos un archivo para unir.")

    cmd = [ffmpeg, "-y"]
    for segment in segments:
        cmd += _segment_input_args(segment)

    normalizados = []
    for i in range(len(segments)):
        etiqueta = f"n{i}"
        # loudnorm primero, aformat después: así el formato queda fijado
        # justo antes del crossfade sin importar si loudnorm cambia algo
        # internamente -- si fuera al revés, un loudnorm que alterase el
        # formato podría dejar dos entradas de acrossfade sin homogeneizar.
        cmd_filtro = f"[{i}:a]{_LOUDNORM},{_AFORMAT}[{etiqueta}]"
        normalizados.append(cmd_filtro)

    if len(segments) == 1:
        salida_final = "n0"
        filtro_completo = ";".join(normalizados)
    else:
        cadena = list(normalizados)
        previo = "n0"
        for i in range(1, len(segments)):
            actual = f"n{i}"
            etiqueta_salida = f"cf{i}"
            cadena.append(
                f"[{previo}][{actual}]acrossfade=d={fade_seconds}:c1=tri:c2=tri[{etiqueta_salida}]"
            )
            previo = etiqueta_salida
        salida_final = previo
        filtro_completo = ";".join(cadena)

    cmd += [
        "-filter_complex", filtro_completo,
        "-map", f"[{salida_final}]",
        "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
        # Progreso legible por línea en stdout (out_time_ms=...), para que
        # AudioEditWorker pueda calcular un % real en vez de una barra
        # indeterminada -- ver AudioEditWorker.run().
        "-progress", "pipe:1", "-nostats",
        output_path,
    ]
    return cmd


def validate_segments(segments: list) -> "str | None":
    """Mensaje de error si algún segmento tiene el fin marcado antes (o
    igual) que el inicio -- típico de marcar los botones en el orden
    equivocado. None si todos son válidos. Solo puede comprobar los
    segmentos con ambas marcas puestas: sin el fin marcado no hay forma de
    saber la duración real del archivo sin decodificarlo entero."""
    for segment in segments:
        if segment.start_ms is not None and segment.end_ms is not None:
            if segment.start_ms >= segment.end_ms:
                nombre = os.path.basename(segment.path)
                return f"«{nombre}»: el fin marcado no puede ser anterior (o igual) al inicio."
    return None


def estimated_output_seconds(segments: list, fade_seconds: float) -> float:
    """Duración aproximada del resultado: suma de cada segmento menos el
    tramo que 'come' cada fundido (uno por unión entre segmentos consecutivos).
    Solo para mostrar una estimación en la UI -- no se usa para el comando ffmpeg."""
    total = 0.0
    for segment in segments:
        if segment.end_ms is not None:
            total += max(0, segment.end_ms - (segment.start_ms or 0)) / 1000
    if len(segments) > 1:
        total -= fade_seconds * (len(segments) - 1)
    return max(0.0, total)


def _parse_out_time_ms(linea: str) -> "int | None":
    """Interpreta una línea de progreso de ffmpeg ('-progress pipe:1'):
    'out_time_ms=12345000' (microsegundos, pese al nombre -- así lo emite
    ffmpeg desde hace años, ver su documentación de -progress) o
    'out_time_us=12345000'. Devuelve milisegundos, o None si la línea no es
    ninguno de los dos campos."""
    if linea.startswith("out_time_ms=") or linea.startswith("out_time_us="):
        _, _, valor = linea.partition("=")
        try:
            return int(valor) // 1000
        except ValueError:
            return None
    return None


class AudioEditWorker(QThread):
    """
    Ejecuta build_join_command() en segundo plano.

    Señales:
      progress(frac: float)       -> avance 0.0-1.0 (solo si se dio
                                      expected_total_ms > 0; si no, nunca
                                      se emite y la UI debe mostrar un
                                      progreso indeterminado)
      finished_ok(output_path: str)
      failed(mensaje: str)        -> "__cancelled__" si fue el usuario
    """
    progress = Signal(float)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self, segments: list, fade_seconds: float, output_path: str,
        expected_total_ms: int = 0, parent=None,
    ):
        super().__init__(parent)
        self.segments = list(segments)
        self.fade_seconds = fade_seconds
        self.output_path = output_path
        self.expected_total_ms = expected_total_ms
        self._process = None
        self._cancelado = False
        self._log_fh = None

    def cancel(self):
        self._cancelado = True
        proceso = self._process
        if proceso is not None:
            try:
                proceso.terminate()
            except Exception:
                pass

    def run(self):
        ffmpeg = get_ffmpeg_exe()
        if ffmpeg is None:
            self.failed.emit("No se encontró ffmpeg, necesario para unir los MP3.")
            return

        if not self.segments:
            self.failed.emit("Hace falta al menos un archivo para unir.")
            return

        error_marcas = validate_segments(self.segments)
        if error_marcas:
            self.failed.emit(error_marcas)
            return

        dest_dir = os.path.dirname(self.output_path) or "."
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as exc:
            self.failed.emit(f"No se pudo crear la carpeta de destino: {exc}")
            return

        fd, output_tmp = tempfile.mkstemp(prefix="tdtvip_edit_", suffix=".mp3", dir=dest_dir)
        os.close(fd)
        cmd = build_join_command(self.segments, self.fade_seconds, output_tmp, ffmpeg)

        # stderr a un archivo, no a un segundo PIPE: leyendo stdout (progreso)
        # línea a línea de forma síncrona, un stderr por PIPE que se llenara
        # sin nadie leyéndolo bloquearía a ffmpeg entero (deadlock clásico
        # con dos pipes y un solo lector) -- mismo motivo que ya documenta
        # core/recorder.py para su propio log de stderr.
        log_path = output_tmp + ".log"
        try:
            self._log_fh = open(log_path, "wb")
        except OSError:
            self._log_fh = None

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=self._log_fh or subprocess.DEVNULL,
                text=True, errors="replace", bufsize=1,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            log.exception("No se pudo arrancar ffmpeg para unir MP3 (cmd: %s)", cmd)
            self._close_log()
            self._cleanup_tmp(output_tmp)
            self._cleanup_tmp(log_path)
            self.failed.emit(str(exc))
            return

        # cancel() pudo llegar justo antes de que Popen() dejara listo
        # self._process -- sin este chequeo, esa ventana dejaría correr la
        # unión entera (que puede tardar) ignorando la cancelación.
        if self._cancelado:
            try:
                self._process.terminate()
            except Exception:
                pass

        for linea in self._process.stdout:
            if self._cancelado:
                continue
            ms = _parse_out_time_ms(linea.strip())
            if ms is not None and self.expected_total_ms > 0:
                frac = min(1.0, ms / self.expected_total_ms)
                self.progress.emit(frac)

        returncode = self._process.wait()
        self._process = None
        self._close_log()

        if self._cancelado:
            self._cleanup_tmp(output_tmp)
            self._cleanup_tmp(log_path)
            self.failed.emit("__cancelled__")
            return

        if returncode != 0:
            detalle = self._log_tail(log_path)
            self._cleanup_tmp(output_tmp)
            self._cleanup_tmp(log_path)
            log.warning("ffmpeg falló uniendo MP3 (cmd: %s): %s", cmd, detalle)
            self.failed.emit(detalle or "ffmpeg no pudo unir los archivos.")
            return

        self._cleanup_tmp(log_path)
        try:
            os.replace(output_tmp, self.output_path)
        except OSError as exc:
            log.exception("No se pudo renombrar %s a %s", output_tmp, self.output_path)
            self._cleanup_tmp(output_tmp)
            self.failed.emit(f"Unión completada pero no se pudo guardar: {exc}")
            return

        self.progress.emit(1.0)
        self.finished_ok.emit(self.output_path)

    def _close_log(self):
        if self._log_fh:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None

    @staticmethod
    def _log_tail(log_path: str) -> str:
        try:
            with open(log_path, encoding="utf-8", errors="ignore") as fh:
                texto = fh.read()
        except OSError:
            return ""
        lineas = [linea for linea in texto.strip().splitlines() if linea.strip()]
        return "\n".join(lineas[-3:])

    @staticmethod
    def _cleanup_tmp(path: str):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

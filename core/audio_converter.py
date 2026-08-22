"""
Conversión de archivos de audio a MP3 (320kbps) mediante ffmpeg.

INPUT_EXTENSIONS cubre los contenedores/codecs de audio que ffmpeg sabe
decodificar de forma habitual (sin entrar en contenedores de vídeo). Solo
disponible en la versión con licencia (ver ui/download_panel.py, que solo
se construye ahí). Sigue el mismo patrón que core/recorder.py para lanzar
y cerrar ffmpeg sin dejar procesos huérfanos. Para .webm/.mka ffmpeg
extrae solo el audio (`-vn` ya descarta cualquier pista de vídeo, si la
hubiera).

Coder By X@R
"""
import os
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

from core.config import get_ffmpeg_exe
from core.logger import get_logger

log = get_logger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

MP3_BITRATE = "320k"
INPUT_EXTENSIONS = (
    ".wav", ".flac", ".aif", ".aiff", ".opus", ".webm", ".ogg", ".oga",
    ".mka", ".m4a", ".aac", ".wma", ".ape", ".wv", ".mp2", ".ac3", ".amr",
)


def build_output_path(input_path: str, dest_dir: str) -> str:
    """Nombre de salida en dest_dir a partir del nombre del archivo de entrada,
    sin sobrescribir uno ya existente (añade ' (2)', ' (3)'...)."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    candidato = os.path.join(dest_dir, f"{base}.mp3")
    contador = 2
    while os.path.exists(candidato):
        candidato = os.path.join(dest_dir, f"{base} ({contador}).mp3")
        contador += 1
    return candidato


def _build_command(ffmpeg: str, input_path: str, output_tmp: str) -> list:
    return [
        ffmpeg, "-y",
        "-i", input_path,
        "-vn",
        "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
        output_tmp,
    ]


class AudioConvertWorker(QThread):
    """
    Convierte una lista de archivos WAV/FLAC a MP3, uno a uno.

    Señales:
      progress(idx: int, total: int, nombre: str) -> va a empezar el archivo idx (0-based)
      file_done(input_path: str, output_path: str) -> un archivo terminó bien
      file_failed(input_path: str, mensaje: str)    -> un archivo falló (se sigue con el resto)
      finished_all()                                -> terminó todo el lote (incluso si hubo fallos)
      cancelled()                                   -> se canceló el lote entero
    """
    progress = Signal(int, int, str)
    file_done = Signal(str, str)
    file_failed = Signal(str, str)
    finished_all = Signal()
    cancelled = Signal()

    def __init__(self, input_paths: list, dest_dir: str, parent=None):
        super().__init__(parent)
        self.input_paths = list(input_paths)
        self.dest_dir = dest_dir
        self._process = None
        self._cancelado = False

    def cancel(self):
        self._cancelado = True
        proceso = self._process
        if proceso is not None:
            try:
                proceso.terminate()
            except Exception:
                pass

    def run(self):
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
        except OSError as exc:
            for input_path in self.input_paths:
                self.file_failed.emit(input_path, f"No se pudo crear la carpeta de destino: {exc}")
            self.finished_all.emit()
            return

        ffmpeg = get_ffmpeg_exe()
        if ffmpeg is None:
            for input_path in self.input_paths:
                self.file_failed.emit(input_path, "No se encontró ffmpeg, necesario para convertir.")
            self.finished_all.emit()
            return

        total = len(self.input_paths)
        for idx, input_path in enumerate(self.input_paths):
            if self._cancelado:
                self.cancelled.emit()
                return
            self.progress.emit(idx, total, os.path.basename(input_path))
            self._convert_one(ffmpeg, input_path)

        if self._cancelado:
            self.cancelled.emit()
            return
        self.finished_all.emit()

    def _convert_one(self, ffmpeg: str, input_path: str):
        output_path = build_output_path(input_path, self.dest_dir)
        fd, output_tmp = tempfile.mkstemp(
            prefix="tdtvip_conv_", suffix=".mp3", dir=self.dest_dir
        )
        os.close(fd)

        cmd = _build_command(ffmpeg, input_path, output_tmp)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            log.exception("No se pudo arrancar ffmpeg para convertir %s", input_path)
            self._cleanup_tmp(output_tmp)
            self.file_failed.emit(input_path, str(exc))
            return

        # cancel() pudo llegar justo entre el chequeo de _cancelado del
        # bucle en run() y que Popen() dejara listo self._process -- sin
        # este segundo chequeo, esa ventana (pequeña pero real) dejaría
        # correr esta conversión entera en vez de cortarla.
        if self._cancelado:
            try:
                self._process.terminate()
            except Exception:
                pass

        returncode = self._process.wait()
        self._process = None

        if self._cancelado:
            self._cleanup_tmp(output_tmp)
            return

        if returncode != 0:
            self._cleanup_tmp(output_tmp)
            self.file_failed.emit(input_path, "ffmpeg no pudo convertir el archivo.")
            return

        try:
            os.replace(output_tmp, output_path)
        except OSError as exc:
            log.exception("No se pudo renombrar %s a %s", output_tmp, output_path)
            self._cleanup_tmp(output_tmp)
            self.file_failed.emit(input_path, f"Conversión completada pero no se pudo guardar: {exc}")
            return

        self.file_done.emit(input_path, output_path)

    @staticmethod
    def _cleanup_tmp(path: str):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

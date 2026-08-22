"""
Lectura y escritura de metadatos (tags ID3) y duración de archivos MP3, vía
ffmpeg por subproceso (LGPL, ya empaquetado con la app).

A propósito NO se usa mutagen (la librería Python obvia para esto): es
GPL, y enlazarla dentro de una aplicación con licencias de pago obligaría
a liberar el conjunto bajo GPL -- conflicto directo con el modelo de
negocio de esta app. ffmpeg, al ir por subproceso (no enlazado), no tiene
ese problema, igual que ya pasa con yt-dlp.exe/slskd.

Escribir tags es un remux (-c copy): reescribe el contenedor sin
recodificar el audio, así que es instantáneo y sin pérdida. No se puede
escribir "in situ": se escribe a un archivo temporal en la misma carpeta y
se renombra encima del original (mismo patrón atómico que el resto de la
app).

Leer duración/tags parseando 'ffmpeg -i archivo' es la alternativa a
ffprobe.exe, deliberadamente no empaquetado (~97 MB, ver TDTRadioVIP.spec) --
ffmpeg imprime la misma información a stderr antes de quejarse de que
falta un archivo de salida, que es justo lo que se ignora aquí.

Coder By X@R
"""
import os
import re
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

from core.config import get_ffmpeg_exe
from core.logger import get_logger

log = get_logger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_PROBE_TIMEOUT_SECONDS = 15

# Clave ffmpeg -> etiqueta en español para la UI. El orden es el orden de
# aparición en el formulario de edición.
TAG_FIELDS = (
    ("title", "Título"),
    ("artist", "Artista"),
    ("album", "Álbum"),
    ("date", "Año"),
    ("genre", "Género"),
    ("track", "Pista"),
)
TAG_KEYS = tuple(clave for clave, _ in TAG_FIELDS)

_METADATA_HEADER_RE = re.compile(r"^  Metadata:\s*$")
_METADATA_LINE_RE = re.compile(r"^    (\S.*?)\s*: (.*)$")
_DURATION_RE = re.compile(r"^  Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")


def _parse_probe_output(texto: str) -> dict:
    """
    Extrae duración y tags de formato (no de stream) de la salida de
    'ffmpeg -i archivo'. Solo el primer bloque 'Metadata:' (indentado con
    2 espacios, el que sigue a "Input #0,...") cuenta como tags del
    archivo -- el resto de bloques 'Metadata:' que puedan aparecer bajo
    cada Stream (indentados más) son metadatos técnicos (encoder...), no
    tags editables por el usuario.
    """
    duration_ms = None
    tags = {}
    en_metadata_formato = False
    for linea in texto.splitlines():
        if _METADATA_HEADER_RE.match(linea):
            en_metadata_formato = True
            continue
        if en_metadata_formato:
            m = _METADATA_LINE_RE.match(linea)
            if m:
                clave, valor = m.group(1).strip().lower(), m.group(2).strip()
                tags[clave] = valor
                continue
            en_metadata_formato = False
        m_dur = _DURATION_RE.match(linea)
        if m_dur:
            horas, minutos, segundos = m_dur.groups()
            duration_ms = int((int(horas) * 3600 + int(minutos) * 60 + float(segundos)) * 1000)
    return {"duration_ms": duration_ms, "tags": tags}


def probe(path: str) -> dict:
    """
    {"duration_ms": int|None, "tags": {clave_ffmpeg: valor, ...}}.

    No lanza excepción si ffmpeg falla o no está disponible: devuelve
    valores vacíos, para que quien llame pueda mostrar "sin datos" en vez
    de reventar. Pensada para llamarse desde un FetchWorker (ver
    ui/fetch_worker.py), nunca desde el hilo de la interfaz -- aunque no
    decodifica audio, sigue siendo E/S de disco más arranque de proceso.
    """
    ffmpeg = get_ffmpeg_exe()
    if ffmpeg is None:
        return {"duration_ms": None, "tags": {}}
    try:
        resultado = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, errors="replace",
            timeout=_PROBE_TIMEOUT_SECONDS,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("No se pudo leer info de %s con ffmpeg", path, exc_info=True)
        return {"duration_ms": None, "tags": {}}
    return _parse_probe_output(resultado.stderr or "")


def build_write_tags_command(ffmpeg: str, input_path: str, output_tmp: str, tags: dict) -> list:
    """
    tags: {clave_ffmpeg: valor}. Una clave ausente o con valor vacío borra
    ese tag en la salida (semántica propia de ffmpeg para -metadata clave=).
    """
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-map", "0", "-c", "copy",
        "-id3v2_version", "3", "-write_id3v1", "1",
    ]
    for clave in TAG_KEYS:
        cmd += ["-metadata", f"{clave}={tags.get(clave, '')}"]
    cmd.append(output_tmp)
    return cmd


class Mp3TagWriteWorker(QThread):
    """
    Reescribe los tags de un único MP3 (remux con -c copy) y lo deja en el
    mismo path que el original (temporal + rename atómico).

    Señales: finished_ok(path) / failed(mensaje).
    """
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, path: str, tags: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.tags = dict(tags)
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
        ffmpeg = get_ffmpeg_exe()
        if ffmpeg is None:
            self.failed.emit("No se encontró ffmpeg, necesario para guardar los tags.")
            return

        dest_dir = os.path.dirname(self.path) or "."
        _, ext = os.path.splitext(self.path)
        # La extensión del temporal tiene que seguir siendo .mp3 (no .tmp):
        # ffmpeg deduce el contenedor de salida por la extensión del propio
        # nombre de archivo, y con .tmp falla con "Unable to find a suitable
        # output format". mkstemp también evita colisión si dos guardados
        # del mismo archivo llegaran a solaparse.
        fd, output_tmp = tempfile.mkstemp(prefix="tdtvip_tag_", suffix=ext or ".mp3", dir=dest_dir)
        os.close(fd)

        cmd = build_write_tags_command(ffmpeg, self.path, output_tmp, self.tags)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            log.exception("No se pudo arrancar ffmpeg para guardar tags de %s", self.path)
            self._cleanup_tmp(output_tmp)
            self.failed.emit(str(exc))
            return

        if self._cancelado:
            try:
                self._process.terminate()
            except Exception:
                pass

        _, stderr = self._process.communicate()
        returncode = self._process.returncode
        self._process = None

        if self._cancelado:
            self._cleanup_tmp(output_tmp)
            self.failed.emit("__cancelled__")
            return

        if returncode != 0:
            self._cleanup_tmp(output_tmp)
            detalle = (stderr or "").strip().splitlines()[-3:]
            log.warning("ffmpeg falló guardando tags (cmd: %s): %s", cmd, detalle)
            self.failed.emit("\n".join(detalle) or "ffmpeg no pudo guardar los tags.")
            return

        try:
            os.replace(output_tmp, self.path)
        except OSError as exc:
            log.exception("No se pudo renombrar %s a %s", output_tmp, self.path)
            self._cleanup_tmp(output_tmp)
            self.failed.emit(f"Tags guardados pero no se pudo reemplazar el archivo: {exc}")
            return

        self.finished_ok.emit(self.path)

    @staticmethod
    def _cleanup_tmp(path: str):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

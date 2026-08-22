"""
Descarga de vídeos por URL: vídeo (MP4) o solo audio (MP3).

Se usa el EJECUTABLE oficial yt-dlp.exe (no la librería Python), porque trae
su propio mecanismo de autoactualización: así los cambios que YouTube hace en
su web se recogen solos, sin depender de que publiquemos una versión nueva.

Coder By X@R
"""
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.request

from PySide6.QtCore import QThread, Signal

from core.config import get_app_data_dir, get_ffmpeg_dir
from core.logger import get_logger

log = get_logger(__name__)

YT_DLP_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
YT_DLP_CHECKSUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
MAX_TOOL_DOWNLOAD_BYTES = 100 * 1024 * 1024
UPDATE_CHECK_INTERVAL_SECONDS = 6 * 3600  # no comprobar más de una vez cada 6h
DOWNLOAD_TIMEOUT_SECONDS = 30

# Marca propia para reconocer sin ambigüedad las líneas de progreso de yt-dlp.
_PROG = "@@PROG@@"
_PROGRESS_TEMPLATE = (
    "download:" + _PROG +
    "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s"
)
_POSTPROCESO_PREFIJOS = ("[ExtractAudio]", "[Merger]", "[ffmpeg]", "[VideoConvertor]", "[Fixup")

# Evita que se abra una consola negra al lanzar yt-dlp.exe/ffmpeg desde la GUI.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def _tools_dir():
    d = get_app_data_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_check_file():
    return _tools_dir() / "last_update_check.txt"


def _num(texto):
    """Convierte un campo de yt-dlp a float, o None si viene vacío/'NA'/'None'."""
    if not texto or texto in ("NA", "None"):
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _fmt_velocidad(bps):
    if not bps:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / 1024 / 1024:.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def _fmt_eta(segundos):
    if segundos is None:
        return ""
    segundos = int(segundos)
    if segundos >= 3600:
        return f"faltan {segundos // 3600}h {(segundos % 3600) // 60:02d}m"
    return f"faltan {segundos // 60}:{segundos % 60:02d}"


# --------------------------------------------------------------------------
# Gestión del ejecutable yt-dlp
# --------------------------------------------------------------------------

def ensure_yt_dlp(progress_cb=None) -> str:
    """
    Devuelve la ruta a yt-dlp.exe, descargándolo la primera vez si hace falta.

    Se descarga a un archivo temporal y solo al terminar se renombra al nombre
    definitivo. Así, si se corta la conexión a mitad, no queda un ejecutable
    truncado que luego se daría por válido y rompería todas las descargas.
    """
    exe_path = _tools_dir() / "yt-dlp.exe"
    hash_path = exe_path.with_suffix(".exe.sha256")
    if exe_path.exists() and exe_path.stat().st_size > 0:
        try:
            expected_local = hash_path.read_text(encoding="ascii").strip().lower()
            actual_local = hashlib.sha256(exe_path.read_bytes()).hexdigest()
            if hmac.compare_digest(actual_local, expected_local):
                return str(exe_path)
        except OSError:
            pass
        exe_path.unlink(missing_ok=True)
        hash_path.unlink(missing_ok=True)

    parcial = exe_path.with_suffix(".part")
    peticion = urllib.request.Request(
        YT_DLP_RELEASE_URL, headers={"User-Agent": "TDT-Radio-VIP"}
    )
    try:
        checksum_request = urllib.request.Request(
            YT_DLP_CHECKSUMS_URL, headers={"User-Agent": "TDT-Radio-VIP"}
        )
        with urllib.request.urlopen(checksum_request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            sums = resp.read(2 * 1024 * 1024).decode("ascii", errors="strict")
        expected = next(
            (parts[0].lower() for line in sums.splitlines()
             if len(parts := line.split()) >= 2 and parts[-1].lstrip("*") == "yt-dlp.exe"),
            None,
        )
        if not expected or len(expected) != 64:
            raise RuntimeError("La release oficial no contiene el SHA-256 de yt-dlp.exe")

        digest = hashlib.sha256()
        with urllib.request.urlopen(peticion, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_TOOL_DOWNLOAD_BYTES:
                raise RuntimeError("yt-dlp.exe supera el tamaño máximo permitido")
            bajado = 0
            with open(parcial, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    if bajado + len(chunk) > MAX_TOOL_DOWNLOAD_BYTES:
                        raise RuntimeError("yt-dlp.exe supera el tamaño máximo permitido")
                    fh.write(chunk)
                    digest.update(chunk)
                    bajado += len(chunk)
                    if progress_cb and total:
                        progress_cb(bajado / total)
        if not hmac.compare_digest(digest.hexdigest(), expected):
            raise RuntimeError("El SHA-256 de yt-dlp.exe no coincide con la release oficial")
        os.replace(parcial, exe_path)
        hash_path.write_text(expected, encoding="ascii")
    except Exception:
        log.exception("Fallo descargando %s a %s", YT_DLP_RELEASE_URL, exe_path)
        try:
            if parcial.exists():
                parcial.unlink()
        except OSError:
            pass
        raise
    return str(exe_path)


def should_check_update() -> bool:
    f = _last_check_file()
    if not f.exists():
        return True
    try:
        last = float(f.read_text().strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) > UPDATE_CHECK_INTERVAL_SECONDS


def mark_update_checked():
    try:
        _last_check_file().write_text(str(time.time()))
    except OSError:
        pass


def self_update_yt_dlp(exe_path: str, timeout: int = 25, cancel_check=None) -> bool:
    """
    Pide a yt-dlp que se autoactualice ('yt-dlp -U'). Si no hay red o falla,
    no es un error fatal: se sigue usando la copia que ya había.

    cancel_check: callable opcional que UpdateCheckWorker sondea para poder
    abortar antes -- con subprocess.run(timeout=...) de antes, cancelar el
    QThread no tenía forma de interrumpir esta llamada, así que cerrar la
    app con una comprobación de actualización en marcha podía bloquear el
    cierre hasta 25s (o dejar el QThread corriendo de fondo si el cierre no
    esperaba tanto, emitiendo su señal `done` contra un panel ya destruido).
    Con Popen + sondeo se puede matar el proceso en cuanto se pide cancelar,
    en vez de esperar a que el propio timeout expire.
    """
    try:
        proceso = subprocess.Popen(
            [exe_path, "-U"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        log.info("yt-dlp -U no pudo autoactualizarse (sin red, o fallo al arrancar); se sigue usando la copia actual", exc_info=True)
        return False

    deadline = time.monotonic() + timeout
    while proceso.poll() is None:
        if time.monotonic() >= deadline or (cancel_check and cancel_check()):
            proceso.kill()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return False
        time.sleep(0.2)
    return proceso.returncode == 0


# --------------------------------------------------------------------------
# Búsqueda multi-fuente (YouTube / SoundCloud / música libre)
# --------------------------------------------------------------------------
#
# yt-dlp acepta "ytsearchN:consulta" / "scsearchN:consulta" como si fueran
# una URL más -- así que la búsqueda no necesita ninguna librería ni API key
# nueva, solo el mismo yt-dlp.exe que ya usa DownloadWorker. No existe un
# extractor de Free Music Archive/Jamendo en yt-dlp, así que "FMA / Jamendo"
# no es una fuente real: es una búsqueda en YouTube con términos añadidos
# para sesgar los resultados hacia música de licencia libre. Se avisa aquí
# porque no es evidente por el nombre.

SEARCH_SOURCES = ["Todo", "YouTube", "SoundCloud", "FMA / Jamendo"]

_SEARCH_PREFIXES = {
    "Todo": "ytsearch",
    "YouTube": "ytsearch",
    "SoundCloud": "scsearch",
    "FMA / Jamendo": "ytsearch",
}
_SEARCH_SUFFIXES = {
    "FMA / Jamendo": " creative commons free music",
}
_SEARCH_MAX_RESULTS = 8
# "ytsearchN:"/"scsearchN:" hacen una extracción COMPLETA por cada uno de
# los N resultados (no es una búsqueda ligera) -- con red lenta o cuando
# YouTube va cuesta arriba, puede tardar sin dar señales de vida. Sin este
# timeout, un yt-dlp realmente colgado dejaba el SearchWorker "corriendo"
# para siempre: no emitía ni resultados ni error, y _start_search() bloqueaba
# cualquier búsqueda posterior en silencio (reportado: "se queda buscando
# y no saca nada, y aunque busques otra cosa sigue en lo mismo").
_SEARCH_TIMEOUT_SECONDS = 45


def _build_search_command(exe_path: str, query: str, source: str, max_results: int) -> list:
    prefijo = _SEARCH_PREFIXES.get(source, "ytsearch")
    sufijo = _SEARCH_SUFFIXES.get(source, "")
    consulta = f"{query}{sufijo}"
    return [
        exe_path, f"{prefijo}{max_results}:{consulta}",
        "--dump-json", "--no-playlist", "--no-warnings", "--quiet",
    ]


def _parse_search_line(linea: str, source: str) -> "dict | None":
    """
    Convierte una línea --dump-json de yt-dlp en un resultado de búsqueda,
    o None si hay que descartarla (línea inválida, sin URL, o pista de
    SoundCloud privada/eliminada o en preview restringido).
    """
    try:
        info = json.loads(linea)
    except json.JSONDecodeError:
        return None

    url = info.get("webpage_url") or ""
    if not url:
        return None

    extractor = (info.get("extractor_key") or "").lower()
    if "soundcloud" in extractor:
        fuente = "SoundCloud"
    elif "youtube" in extractor:
        # Si se buscó como "FMA / Jamendo" (que en realidad busca en
        # YouTube, ver nota más arriba), se mantiene esa etiqueta en el
        # resultado en vez de mostrar "YouTube".
        fuente = "FMA / Jamendo" if source == "FMA / Jamendo" else "YouTube"
    else:
        fuente = info.get("extractor_key") or source

    duracion = info.get("duration") or 0

    # Pistas privadas/eliminadas de SoundCloud devuelven una URL de API
    # interna en vez de la URL pública normal -- nunca son descargables.
    if "api.soundcloud.com/tracks/" in url.lower():
        return None
    # En SoundCloud, una duración de 30s o menos casi siempre es la señal
    # de un preview restringido (sin sesión iniciada), no la canción
    # completa -- no aplica a otras fuentes, donde un tema corto es legítimo.
    if fuente == "SoundCloud" and 0 < duracion <= 30:
        return None

    minutos, segundos = divmod(int(duracion), 60)
    return {
        "title": info.get("title") or "Sin título",
        "artist": info.get("uploader") or info.get("artist") or "Desconocido",
        "duration": f"{minutos}:{segundos:02d}",
        "source": fuente,
        "url": url,
        "id": info.get("id", ""),
    }


# --------------------------------------------------------------------------
# Hilos de trabajo
# --------------------------------------------------------------------------

class UpdateCheckWorker(QThread):
    """Fuerza (bajo demanda) una comprobación de actualización de yt-dlp.exe."""
    done = Signal(bool, str)  # éxito, mensaje

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelado = False

    def cancel(self):
        self._cancelado = True

    def run(self):
        try:
            exe_path = ensure_yt_dlp()
        except Exception as exc:
            if not self._cancelado:
                self.done.emit(False, f"No se pudo descargar yt-dlp.exe: {exc}")
            return
        if self._cancelado:
            return
        ok = self_update_yt_dlp(exe_path, cancel_check=lambda: self._cancelado)
        mark_update_checked()
        if self._cancelado:
            # No emitir done(): el panel puede estar ya destruyéndose (ver
            # cancel(), llamado desde DownloadPanel.shutdown()).
            return
        if ok:
            self.done.emit(True, "yt-dlp está actualizado a la última versión.")
        else:
            self.done.emit(
                False,
                "No se pudo comprobar actualizaciones (¿sin conexión?). "
                "Se sigue usando la copia actual.",
            )


class DownloadWorker(QThread):
    """
    Descarga una URL en segundo plano usando yt-dlp.exe (externo, autoactualizable).

    Señales:
      progress(frac: float, texto: str)  -> avance 0.0–1.0 y mensaje de estado
      finished_ok(filepath: str)         -> ruta del archivo final (o carpeta destino
                                            si no se pudo determinar con certeza)
      failed(mensaje: str)               -> error ("__cancelled__" si fue el usuario)
    """
    progress = Signal(float, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest_dir: str, as_mp3: bool, parent=None):
        super().__init__(parent)
        self.url = url.strip()
        self.dest_dir = dest_dir
        self.as_mp3 = as_mp3
        self._process = None
        self._cancelado = False
        self._fallo_grave = False

    def cancel(self):
        self._cancelado = True
        proceso = self._process
        if proceso is None:
            return
        try:
            proceso.terminate()
        except Exception:
            pass

    # ---------- ejecución ----------

    def run(self):
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
        except OSError as exc:
            self.failed.emit(f"No se pudo crear la carpeta de destino: {exc}")
            return

        try:
            self.progress.emit(0.0, "Preparando yt-dlp…")
            exe_path = ensure_yt_dlp(
                progress_cb=lambda f: self.progress.emit(
                    f, f"Descargando yt-dlp por primera vez… {f * 100:.0f}%"
                )
            )
        except Exception as exc:
            log.exception("Fallo preparando yt-dlp.exe para la descarga")
            self.failed.emit(
                "No se pudo obtener yt-dlp.exe. Hace falta conexión a internet "
                f"la primera vez que se usa la descarga.\n\nDetalle: {exc}"
            )
            return

        if self._cancelado:
            self.failed.emit("__cancelled__")
            return

        if should_check_update():
            self.progress.emit(0.0, "Comprobando actualizaciones de yt-dlp…")
            self_update_yt_dlp(exe_path)
            mark_update_checked()

        final_path = self._run_download(exe_path)

        if self._cancelado:
            self.failed.emit("__cancelled__")
            return
        if self._fallo_grave:
            return  # el error concreto ya se emitió dentro de _run_download
        self.finished_ok.emit(final_path or self.dest_dir)

    def _construir_comando(self, exe_path: str, ruta_salida_tmp: str):
        cmd = [
            exe_path, self.url,
            "-o", os.path.join(self.dest_dir, "%(title).150s.%(ext)s"),
            "--no-playlist",
            "--newline",
            "--progress",
            "--progress-template", _PROGRESS_TEMPLATE,
            # Ruta definitiva escrita a un archivo aparte: determinista, sin
            # tener que adivinarla entre el resto de la salida de consola.
            "--print-to-file", "after_move:filepath", ruta_salida_tmp,
        ]
        ffmpeg_dir = get_ffmpeg_dir()
        if ffmpeg_dir:
            cmd += ["--ffmpeg-location", ffmpeg_dir]

        if self.as_mp3:
            cmd += [
                "-f", "bestaudio/best",
                "--extract-audio", "--audio-format", "mp3", "--audio-quality", "192K",
            ]
        else:
            cmd += [
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
            ]
        return cmd

    def _run_download(self, exe_path: str):
        fd, ruta_salida_tmp = tempfile.mkstemp(prefix="tdtvip_", suffix=".txt")
        os.close(fd)

        try:
            return self._ejecutar(exe_path, ruta_salida_tmp)
        finally:
            try:
                os.unlink(ruta_salida_tmp)
            except OSError:
                pass

    def _ejecutar(self, exe_path: str, ruta_salida_tmp: str):
        cmd = self._construir_comando(exe_path, ruta_salida_tmp)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                # Sin esto, un título con acentos puede reventar la lectura del
                # flujo a mitad de descarga en Windows (cp1252).
                encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            log.exception("No se pudo arrancar el proceso de descarga (cmd: %s)", cmd)
            self._fallo_grave = True
            self.failed.emit(str(exc))
            return None

        errores = []
        for linea in self._process.stdout:
            linea = linea.strip()
            if not linea or self._cancelado:
                continue
            if linea.startswith(_PROG):
                self._emitir_progreso(linea[len(_PROG):])
            elif linea.startswith(_POSTPROCESO_PREFIJOS):
                self.progress.emit(1.0, "Procesando con ffmpeg…")
            elif linea.upper().startswith("ERROR"):
                errores.append(linea)

        returncode = self._process.wait()

        if self._cancelado:
            # Si ignoró el terminate(), se fuerza el cierre.
            if self._process.poll() is None:
                try:
                    self._process.kill()
                except Exception:
                    pass
            return None

        if returncode != 0:
            self._fallo_grave = True
            self.failed.emit(
                "\n".join(errores[-3:]) or "Error desconocido durante la descarga."
            )
            return None

        return self._leer_ruta_final(ruta_salida_tmp)

    def _emitir_progreso(self, payload: str):
        partes = payload.split("|")
        if len(partes) < 5:
            return
        bajado = _num(partes[0])
        total = _num(partes[1]) or _num(partes[2])
        velocidad = _num(partes[3])
        eta = _num(partes[4])

        frac = (bajado / total) if (bajado and total) else 0.0
        frac = max(0.0, min(1.0, frac))

        detalles = [t for t in (_fmt_velocidad(velocidad), _fmt_eta(eta)) if t]
        sufijo = ("  ·  " + "  ·  ".join(detalles)) if detalles else ""
        self.progress.emit(frac, f"Descargando… {frac * 100:.0f}%{sufijo}")

    @staticmethod
    def _leer_ruta_final(ruta_salida_tmp: str):
        try:
            with open(ruta_salida_tmp, "r", encoding="utf-8", errors="replace") as fh:
                lineas = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return None
        for ruta in reversed(lineas):
            if os.path.isfile(ruta):
                return ruta
        return None


class SearchWorker(QThread):
    """
    Busca música por título/artista en segundo plano (ver SEARCH_SOURCES
    más arriba). El resultado se pasa tal cual a DownloadWorker -- la
    búsqueda solo resuelve una URL descargable, no descarga nada ella misma.

    Señales:
      results(list[dict])  -> resultados (título, artist, duration, source,
                              url, id); lista vacía si no hubo ninguno
      failed(str)           -> error preparando yt-dlp.exe, arrancando el
                              proceso, o timeout ("__cancelled__" si fue el
                              usuario -- mismo convenio que DownloadWorker;
                              una búsqueda sin resultados NO es un fallo,
                              emite results([]))
    """
    results = Signal(list)
    failed = Signal(str)

    def __init__(self, query: str, source: str, parent=None):
        super().__init__(parent)
        self.query = query.strip()
        self.source = source
        self._process = None
        self._cancelado = False
        self._timeout_saltado = False

    def cancel(self):
        self._cancelado = True
        self._matar_proceso()

    def _matar_proceso(self):
        proceso = self._process
        if proceso is not None:
            try:
                proceso.kill()
            except Exception:
                pass

    def run(self):
        if not self.query:
            self.results.emit([])
            return

        try:
            exe_path = ensure_yt_dlp()
        except Exception as exc:
            log.exception("Fallo preparando yt-dlp.exe para buscar")
            self.failed.emit(
                "No se pudo obtener yt-dlp.exe. Hace falta conexión a internet "
                f"la primera vez que se usa la búsqueda.\n\nDetalle: {exc}"
            )
            return

        if self._cancelado:
            self.failed.emit("__cancelled__")
            return

        cmd = _build_search_command(exe_path, self.query, self.source, _SEARCH_MAX_RESULTS)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            log.exception("No se pudo arrancar yt-dlp para buscar (cmd: %s)", cmd)
            self.failed.emit(str(exc))
            return

        # Vigilante en un hilo aparte: si yt-dlp se queda colgado de verdad
        # (red intermitente, YouTube poniendo pegas...) esto es lo único que
        # saca al proceso de en medio -- el bucle de abajo, por su cuenta,
        # se quedaría esperando líneas para siempre.
        def _por_timeout():
            self._timeout_saltado = True
            self._matar_proceso()

        vigilante = threading.Timer(_SEARCH_TIMEOUT_SECONDS, _por_timeout)
        vigilante.daemon = True
        vigilante.start()

        encontrados = []
        try:
            for linea in self._process.stdout:
                if self._cancelado or self._timeout_saltado:
                    break
                linea = linea.strip()
                if not linea:
                    continue
                resultado = _parse_search_line(linea, self.source)
                if resultado:
                    encontrados.append(resultado)
        finally:
            vigilante.cancel()

        self._process.wait()

        if self._cancelado:
            self.failed.emit("__cancelled__")
        elif self._timeout_saltado:
            self.failed.emit(
                f"La búsqueda tardó más de {_SEARCH_TIMEOUT_SECONDS}s y se "
                "canceló. Puede que la fuente esté saturada o la conexión "
                "vaya lenta -- prueba de nuevo o con menos resultados."
            )
        else:
            self.results.emit(encontrados)

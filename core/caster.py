"""
Envío de contenido (canal/emisora en directo o archivo descargado) a
Chromecast, Android TV / Google TV, o cualquier TV con Google Cast
integrado, mediante pychromecast.

pychromecast (y zeroconf, su dependencia) se importan de forma perezosa,
dentro de las funciones que de verdad los usan — no aquí arriba. Con el
import a nivel de módulo, abrir la app pagaba ese coste en cada arranque
aunque esa sesión no se usara Chromecast ni una vez.

Coder By X@R
"""
import mimetypes
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QThread, Signal

from core.logger import get_logger

log = get_logger(__name__)

def pychromecast_available() -> bool:
    """
    Antes esto era una constante calculada al cargar el módulo
    (PYCHROMECAST_AVAILABLE = pychromecast is not None), lo cual obligaba a
    intentar el import de pychromecast en cuanto algo importaba
    core.caster — exactamente el coste de arranque que queríamos evitar.
    Como función, el intento de import solo ocurre cuando alguien la llama
    de verdad (al abrir el diálogo de Chromecast), no al arrancar la app.
    """
    try:
        import pychromecast  # noqa: F401
        return True
    except ImportError:
        return False


def guess_stream_content_type(url: str, kind: str = "") -> str:
    """Adivina el content-type para un canal/emisora en directo a partir de la URL."""
    lower = url.lower().split("?")[0]
    if lower.endswith(".m3u8") or "m3u8" in lower:
        return "application/x-mpegURL"
    if lower.endswith(".mpd"):
        return "application/dash+xml"
    if lower.endswith(".mp3"):
        return "audio/mp3"
    if lower.endswith((".aac", ".m4a")):
        return "audio/aac"
    if kind == "radio":
        return "audio/mp3"
    return "video/mp4"


def _local_lan_ip() -> str:
    """IP de este PC en la red local (la que la TV puede alcanzar; no 127.0.0.1)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class _SingleFileHandler(BaseHTTPRequestHandler):
    """
    Handler HTTP que sirve un único archivo local con soporte real de rangos
    (HTTP 206). El Chromecast pide rangos para poder avanzar/retroceder y
    para reproducir archivos grandes, y manda un HEAD previo para sondear
    tipo y tamaño: ambos casos deben responderse correctamente.
    """
    filepath = ""
    content_type = "application/octet-stream"
    protocol_version = "HTTP/1.1"  # requerido para que el rango/keep-alive funcionen

    def _parse_range(self, size):
        """Devuelve (inicio, fin) inclusivos, o None si no hay Range utilizable."""
        header = self.headers.get("Range")
        if not header:
            return None
        match = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
        if not match:
            return None
        primero, ultimo = match.group(1), match.group(2)
        if not primero and not ultimo:
            return None
        if not primero:
            # Forma sufijo: "bytes=-N" -> los últimos N bytes.
            n = int(ultimo)
            if n <= 0:
                return None
            inicio, fin = max(0, size - n), size - 1
        else:
            inicio = int(primero)
            fin = min(int(ultimo), size - 1) if ultimo else size - 1
        if inicio > fin or inicio >= size:
            return None
        return inicio, fin

    def _responder(self, con_cuerpo: bool):
        try:
            size = os.path.getsize(self.filepath)
        except OSError:
            self.send_error(404, "File not found")
            return

        rango = self._parse_range(size)
        if rango is None and self.headers.get("Range"):
            # Había cabecera Range pero es inválida o está fuera del archivo.
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if rango:
            inicio, fin = rango
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{size}")
        else:
            inicio, fin = 0, size - 1
            self.send_response(200)

        longitud = fin - inicio + 1
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(longitud))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        if not con_cuerpo:
            return

        try:
            with open(self.filepath, "rb") as fh:
                fh.seek(inicio)
                restante = longitud
                while restante > 0:
                    chunk = fh.read(min(65536, restante))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    restante -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # La TV cortó la conexión (pausa, stop, zapping): no es un error.
            pass

    def do_GET(self):
        self._responder(con_cuerpo=True)

    def do_HEAD(self):
        self._responder(con_cuerpo=False)

    def log_message(self, format_str, *args):  # noqa: A002 - silenciar logs de consola
        pass


class LocalFileServer:
    """
    Servidor HTTP en segundo plano para exponer un archivo local en la red,
    de forma que un Chromecast (que no puede leer tu disco) pueda reproducirlo.
    """

    def __init__(self):
        self._httpd = None
        self._thread = None
        self.port = None

    def serve(self, filepath: str):
        """Arranca el servidor para 'filepath'. Devuelve (url_lan, content_type)."""
        self.stop()
        content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"

        handler_cls = type(
            "_BoundFileHandler", (_SingleFileHandler,),
            {"filepath": filepath, "content_type": content_type},
        )
        self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), handler_cls)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

        filename = os.path.basename(filepath)
        url = f"http://{_local_lan_ip()}:{self.port}/{filename}"
        return url, content_type

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except OSError:
                pass
            self._httpd = None
            self._thread = None


class CastDiscoveryWorker(QThread):
    """Busca Chromecasts / TVs con Google Cast en la red local (Wi-Fi/LAN)."""
    found = Signal(list)  # lista de nombres amigables (str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = []
        self._browser = None

    def run(self):
        try:
            import pychromecast
        except ImportError:
            self.found.emit([])
            return
        try:
            chromecasts, browser = pychromecast.get_chromecasts(timeout=8)
        except Exception:
            log.exception("Fallo al buscar dispositivos Chromecast en la red")
            self.found.emit([])
            return
        self.devices = chromecasts
        self._browser = browser
        self.found.emit([cc.name for cc in chromecasts])

    def device_by_name(self, name: str):
        for cc in self.devices:
            if cc.name == name:
                return cc
        return None

    def stop_discovery(self):
        """
        Cierra el explorador zeroconf. Es idempotente: puede llamarse varias
        veces sin efectos adversos. IMPRESCINDIBLE llamarlo al terminar, o se
        quedan sockets abiertos acumulándose en cada búsqueda.
        """
        browser, self._browser = self._browser, None
        if browser is not None:
            try:
                import pychromecast
                pychromecast.discovery.stop_discovery(browser)
            except Exception:
                log.exception("Fallo al detener el descubrimiento de Chromecast")


class CastSession:
    """Conexión activa con un Chromecast/TV y control de qué se le envía."""

    def __init__(self):
        self.device = None
        self.device_name = None
        self.file_server = LocalFileServer()

    def connect(self, device):
        device.wait(timeout=10)
        self.device = device
        self.device_name = device.name

    def cast_url(self, url: str, content_type: str, title: str = ""):
        if self.device is None:
            raise RuntimeError("No hay ningún dispositivo conectado.")
        mc = self.device.media_controller
        mc.play_media(url, content_type, title=title or None)
        mc.block_until_active(timeout=10)

    def cast_local_file(self, filepath: str, title: str = ""):
        url, content_type = self.file_server.serve(filepath)
        self.cast_url(url, content_type, title=title)

    def stop(self):
        if self.device is not None:
            try:
                self.device.media_controller.stop()
                self.device.quit_app()
            except Exception:
                log.exception(
                    "Fallo al detener la reproducción en el dispositivo %s", self.device_name
                )
        self.file_server.stop()

    def disconnect(self):
        self.stop()
        self.device = None
        self.device_name = None

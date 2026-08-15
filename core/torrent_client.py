"""
Cliente de torrents — vía libtorrent (bindings Python), en el mismo proceso
de la app.

A diferencia del enfoque anterior con aria2c (un .exe empaquetado que se
arrancaba como proceso aparte y se controlaba por JSON-RPC sobre HTTP
local), libtorrent es una librería C++ con bindings Python que corre
DENTRO del proceso de la app: no hay ningún ejecutable que empaquetar,
arrancar, vigilar ni apagar limpiamente al cerrar — se instala como
cualquier otra dependencia de pip y desaparece con el objeto Python. Sigue
cumpliendo el mismo principio que ffmpeg/aria2c antes: el usuario no
instala ni configura nada.

Coder By X@R
"""
import secrets
from dataclasses import dataclass
from typing import Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)

try:
    import libtorrent as lt
except Exception as _exc:  # pragma: no cover - solo si falta el paquete
    lt = None
    LIBTORRENT_IMPORT_ERROR = str(_exc)
else:
    LIBTORRENT_IMPORT_ERROR = ""

# Trackers públicos conocidos y estables, AÑADIDOS a los que ya traiga cada
# torrent/magnet (se suman a la lista propia del .torrent o del magnet, no
# la sustituyen). Motivo: muchos magnet links de fuentes públicas apenas
# traen tracker propio y dependen casi del todo de DHT/PEX para encontrar
# pares -- con pocos pares detectados, la velocidad se resiente aunque el
# resto de la configuración sea buena. No sustituye a DHT/PEX/LSD (ver
# ajustes en conectar()), es una vía más de descubrimiento de pares.
_TRACKERS_PUBLICOS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
]

_NOMBRE_PENDIENTE = "(obteniendo nombre…)"


@dataclass
class TorrentInfo:
    hash: str
    name: str
    progress: float  # 0.0 a 1.0
    state: str
    dlspeed: int  # bytes/s
    size: int
    eta: int  # segundos; -1 si no se puede estimar
    upspeed: int = 0  # bytes/s
    # Peers a los que libtorrent está conectado ahora mismo para este
    # torrent (status.num_peers) -- igual que con aria2 antes, no hay un
    # "N de M" total, solo cuántos hay conectados en este momento.
    peers: int = 0


def paquete_disponible() -> bool:
    """Antes comprobaba si aria2c.exe venía empaquetado con la app; ahora
    comprueba si el paquete Python 'libtorrent' se pudo importar -- sigue
    sin depender de nada que el usuario tenga que instalar aparte, solo
    que ahora es una dependencia de pip normal en vez de un binario."""
    return lt is not None


def _estado_legible(status) -> str:
    """Traduce el estado nativo de libtorrent al mismo vocabulario que ya
    esperaba la interfaz (ui/torrent_panel.py, heredado de qBittorrent vía
    la capa de aria2 anterior), para no tener que tocar esa parte al
    cambiar de motor por debajo."""
    error_msg = ""
    try:
        if status.errc and status.errc.value():
            error_msg = status.errc.message()
    except Exception:
        error_msg = getattr(status, "error", "") or ""
    if error_msg:
        return "error"

    st = status.state
    pausado = bool(status.paused)
    terminado = st in (lt.torrent_status.finished, lt.torrent_status.seeding)

    if st in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data,
              lt.torrent_status.queued_for_checking):
        return "checkingDL"
    if st == lt.torrent_status.downloading_metadata:
        return "metaDL"
    if st == lt.torrent_status.allocating:
        return "queuedDL"

    if terminado:
        if pausado:
            return "pausedUP"
        if status.upload_rate == 0 and status.num_peers == 0:
            return "stalledUP"
        return "uploading"

    # st == downloading, o cualquier otro caso no cubierto arriba
    if pausado:
        return "pausedDL"
    if status.download_rate == 0 and status.num_peers == 0:
        return "stalledDL"
    return "downloading"


class TorrentClient:
    def __init__(self, *_args, **_kwargs):
        # Los parámetros host/port/username/password de enfoques todavía
        # más antiguos (qBittorrent Web UI) ya no aplican; se aceptan y se
        # ignoran para no romper a quien construya TorrentClient() con esa
        # firma vieja.
        self._session = None
        self._handles: Dict[str, "lt.torrent_handle"] = {}
        self._nombres_pendientes: Dict[str, str] = {}

    @property
    def conectado(self) -> bool:
        return self._session is not None

    def conectar(self) -> Optional[str]:
        if self.conectado:
            return None
        if lt is None:
            return f"No se pudo cargar el motor de torrents (libtorrent): {LIBTORRENT_IMPORT_ERROR}"

        try:
            self._session = lt.session({
                "listen_interfaces": "0.0.0.0:6889,[::]:6889",
                "enable_dht": True,
                "enable_lsd": True,
                "enable_natpmp": True,
                "enable_upnp": True,
                # Sin límite propio -- igual que con aria2 antes, no se
                # imponía ningún tope de velocidad por defecto.
                "download_rate_limit": 0,
                "upload_rate_limit": 0,
                # Techo de conexiones total de la sesión más alto que el
                # valor por defecto de libtorrent (200 ya es el default,
                # se deja explícito para que quede documentado el motivo:
                # con varios torrents activos a la vez, 200 se queda corto).
                "connections_limit": 400,
                "active_downloads": -1,
                "active_seeds": -1,
                "active_limit": -1,
            })
        except Exception as exc:
            log.exception("No se pudo crear la sesión de libtorrent")
            self._session = None
            return f"No se pudo arrancar el motor de torrents: {exc}"
        return None

    def anadir(self, magnet_o_ruta: str, carpeta_destino: str) -> Optional[str]:
        if not self.conectado:
            return "El motor de torrents no está en marcha."

        try:
            if magnet_o_ruta.lower().startswith("magnet:"):
                params = lt.parse_magnet_uri(magnet_o_ruta)
            else:
                info = lt.torrent_info(magnet_o_ruta)
                params = lt.add_torrent_params()
                params.ti = info
        except Exception as exc:
            return f"El enlace o archivo .torrent no es válido: {exc}"

        params.save_path = carpeta_destino
        try:
            params.trackers = list(params.trackers) + _TRACKERS_PUBLICOS
        except Exception:
            # Si el binding de esta versión no expone .trackers como lista
            # mutable, se sigue sin los trackers extra en vez de romper el
            # añadido -- DHT/PEX/LSD (activados en conectar()) siguen
            # funcionando igual.
            log.warning("No se pudieron añadir los trackers públicos extra")

        try:
            handle = self._session.add_torrent(params)
        except Exception as exc:
            log.exception("libtorrent rechazó el torrent")
            return f"El motor de torrents rechazó el enlace o archivo: {exc}"

        token = secrets.token_hex(8)
        self._handles[token] = handle
        self._nombres_pendientes[token] = getattr(params, "name", "") or _NOMBRE_PENDIENTE
        return None

    def listar(self) -> List[TorrentInfo]:
        if not self.conectado:
            return []

        resultado = []
        for token, handle in list(self._handles.items()):
            if not handle.is_valid():
                continue
            status = handle.status()

            nombre = status.name or self._nombres_pendientes.get(token) or _NOMBRE_PENDIENTE
            if status.name:
                # En cuanto llegan metadatos el nombre real ya no cambia;
                # se deja de necesitar el provisional.
                self._nombres_pendientes.pop(token, None)

            total = int(status.total_wanted or 0)
            completado = int(status.total_wanted_done or 0)
            progreso = (completado / total) if total > 0 else float(status.progress or 0.0)

            dlspeed = int(status.download_rate or 0)
            eta = int((total - completado) / dlspeed) if dlspeed > 0 else -1

            resultado.append(TorrentInfo(
                hash=token, name=nombre, progress=progreso,
                state=_estado_legible(status),
                dlspeed=dlspeed, size=total, eta=eta,
                upspeed=int(status.upload_rate or 0),
                peers=int(status.num_peers or 0),
            ))
        return resultado

    def pausar(self, hash_: str):
        handle = self._handles.get(hash_)
        if handle is not None and handle.is_valid():
            handle.pause()

    def reanudar(self, hash_: str):
        handle = self._handles.get(hash_)
        if handle is not None and handle.is_valid():
            handle.resume()

    def eliminar(self, hash_: str, borrar_archivos: bool = False):
        """
        A diferencia de aria2 (que nunca llegó a borrar los archivos ya
        descargados al quitar un torrent — quedó documentado como
        limitación sin implementar), libtorrent sí lo soporta de forma
        nativa vía el flag session.delete_files.
        """
        handle = self._handles.pop(hash_, None)
        self._nombres_pendientes.pop(hash_, None)
        if handle is None or not handle.is_valid():
            return
        flags = lt.session.delete_files if borrar_archivos else 0
        self._session.remove_torrent(handle, flags)

    def cerrar(self, on_wait=None):
        """
        Libera la sesión de libtorrent. A diferencia de aria2c.exe antes
        (proceso externo que había que esperar/matar con cuidado para no
        dejarlo huérfano, ver core.recorder.Recorder.stop() para el mismo
        patrón en otro sitio de la app), aquí no hay ningún proceso
        externo que gestionar: libtorrent corre en el propio proceso de la
        app y libera sockets/hilos internos en el destructor de la sesión.

        on_wait: se acepta por compatibilidad con la firma anterior (la
        UI lo pasaba para poder seguir bombeando QApplication.processEvents
        mientras aria2c se apagaba); ya no hace falta invocarlo porque
        cerrar() no bloquea.
        """
        self._handles.clear()
        self._nombres_pendientes.clear()
        self._session = None

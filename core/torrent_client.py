"""
Cliente de torrents — vía aria2c, empaquetado directamente con la app.

A diferencia del enfoque anterior (que dependía de qBittorrent instalado
aparte por el usuario, con su Web UI activada a mano — nada práctico),
esto funciona igual que ffmpeg: un ejecutable que viaja DENTRO de la app,
se arranca solo en segundo plano la primera vez que hace falta, y el
usuario no instala ni configura nada.

aria2c habla JSON-RPC por HTTP local — se usa 'requests' (ya es
dependencia del proyecto) para hablar con él, sin librerías extra que
puedan tener problemas de compatibilidad con la versión de Python.

Coder By X@R
"""
import base64
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

import requests

from core.config import get_aria2_exe, get_app_data_dir
from core.logger import get_logger

log = get_logger(__name__)

RPC_PORT = 6801  # puerto poco común, para minimizar choque con otra cosa
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Trackers públicos conocidos y estables, AÑADIDOS a los que ya traiga cada
# torrent/magnet (aria2 combina las dos listas, no sustituye una por otra).
# Motivo: muchos magnet links de fuentes públicas apenas traen tracker
# propio y dependen casi del todo de DHT/PEX para encontrar pares -- con
# pocos pares detectados, la velocidad se resiente aunque el resto de la
# configuración sea buena. No sustituye a DHT/PEX/LPD (que ya estaban
# activados), es una vía más de descubrimiento de pares.
_TRACKERS_PUBLICOS = ",".join([
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
])

# Traduce los estados de aria2 a los mismos nombres que ya esperaba la
# interfaz (ui/torrent_panel.py), para no tener que tocar esa parte al
# cambiar de motor por debajo.
_ESTADO_ARIA2_A_INTERNO = {
    "active": "downloading",
    "waiting": "queuedDL",
    "paused": "pausedDL",
    "error": "error",
    "complete": "stalledUP",
    "removed": "error",
}


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
    # Peers/servidores a los que aria2 está conectado ahora mismo para este
    # torrent -- a diferencia de Transmission, aria2 no expone aparte cuántos
    # peers hay disponibles en total (solo con los que ya conectó), así que
    # la interfaz solo puede mostrar "conectado a N pares", no "N de M".
    peers: int = 0


def paquete_disponible() -> bool:
    """Antes comprobaba si el paquete Python 'qbittorrent-api' estaba
    instalado; ahora comprueba si aria2c.exe viene empaquetado con la
    app — ya no depende de nada que el usuario tenga que instalar."""
    return get_aria2_exe() is not None


class TorrentClient:
    def __init__(self, *_args, **_kwargs):
        # Los parámetros host/port/username/password del enfoque anterior
        # (para conectar con qBittorrent) ya no aplican; se aceptan y se
        # ignoran para no romper a quien construya TorrentClient() con esa
        # firma antigua.
        self._proceso: Optional[subprocess.Popen] = None
        self._secret = secrets.token_hex(16)
        self._rpc_url = f"http://127.0.0.1:{RPC_PORT}/jsonrpc"

    @property
    def conectado(self) -> bool:
        return self._proceso is not None and self._proceso.poll() is None

    def conectar(self) -> Optional[str]:
        if self.conectado:
            return None
        exe = get_aria2_exe()
        if exe is None:
            return "No se encontró aria2c.exe empaquetado con la aplicación."

        carpeta_incompletos = get_app_data_dir() / "torrents_incompletos"
        carpeta_incompletos.mkdir(parents=True, exist_ok=True)

        try:
            self._proceso = subprocess.Popen(
                [
                    exe,
                    "--enable-rpc",
                    f"--rpc-listen-port={RPC_PORT}",
                    f"--rpc-secret={self._secret}",
                    "--rpc-listen-all=false",
                    "--dir", str(carpeta_incompletos),
                    "--continue=true",
                    "--file-allocation=none",
                    "--bt-enable-lpd=true",
                    "--enable-dht=true",
                    "--enable-dht6=true",
                    "--enable-peer-exchange=true",
                    f"--bt-tracker={_TRACKERS_PUBLICOS}",
                    # Techo de pares por torrent más alto que el valor por
                    # defecto de aria2 (55): con más vías de descubrimiento
                    # (arriba) puede encontrar más pares de los que antes
                    # llegaba a usar, así que subir el techo también importa,
                    # no solo encontrarlos.
                    "--bt-max-peers=130",
                    # Sigue pidiendo más pares al tracker mientras la
                    # velocidad no supere este umbral -- el valor por
                    # defecto (50K) se da por "suficiente" demasiado pronto.
                    "--bt-request-peer-speed-limit=100K",
                    # Caché de escritura más generosa que el valor por
                    # defecto (16M): menos parones de disco al recibir
                    # varias piezas seguidas, sobre todo en discos mecánicos
                    # o unidades de red.
                    "--disk-cache=64M",
                    # Prioriza (sin exigir -- no descarta pares que no lo
                    # soporten) cifrar la conexión BitTorrent: algunos ISP
                    # limitan el tráfico BT detectado como no cifrado.
                    "--bt-min-crypto-level=arc4",
                    "--quiet=true",
                ],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            log.exception("No se pudo arrancar aria2c.exe")
            return f"No se pudo arrancar el motor de torrents: {exc}"

        # Esperar a que el RPC esté escuchando antes de dar por conectado.
        for _ in range(20):
            if self._rpc_call("aria2.getVersion") is not None:
                return None
            time.sleep(0.25)
        return "El motor de torrents no respondió a tiempo al arrancar."

    def _rpc_call(self, method: str, params: Optional[list] = None, timeout: float = 5):
        payload = {
            "jsonrpc": "2.0", "id": "tdtradiovip", "method": method,
            "params": [f"token:{self._secret}"] + (params or []),
        }
        try:
            resp = requests.post(self._rpc_url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return None
        if "error" in data:
            log.warning("aria2 RPC error en %s: %s", method, data["error"])
            return None
        return data.get("result")

    def anadir(self, magnet_o_ruta: str, carpeta_destino: str) -> Optional[str]:
        if not self.conectado:
            return "El motor de torrents no está en marcha."
        opciones = {"dir": carpeta_destino}
        if magnet_o_ruta.lower().startswith("magnet:"):
            resultado = self._rpc_call("aria2.addUri", [[magnet_o_ruta], opciones])
        else:
            try:
                with open(magnet_o_ruta, "rb") as f:
                    contenido_b64 = base64.b64encode(f.read()).decode("ascii")
            except OSError as exc:
                return f"No se pudo leer el archivo .torrent: {exc}"
            resultado = self._rpc_call("aria2.addTorrent", [contenido_b64, [], opciones])
        if resultado is None:
            return "El motor de torrents rechazó el enlace o archivo (¿formato inválido?)."
        return None

    def listar(self) -> List[TorrentInfo]:
        if not self.conectado:
            return []
        activos = self._rpc_call("aria2.tellActive") or []
        esperando = self._rpc_call("aria2.tellWaiting", [0, 200]) or []
        parados = self._rpc_call("aria2.tellStopped", [0, 200]) or []
        return [self._parse_torrent(t) for t in (activos + esperando + parados)]

    @staticmethod
    def _parse_torrent(t: dict) -> TorrentInfo:
        total = int(t.get("totalLength", 0) or 0)
        completado = int(t.get("completedLength", 0) or 0)
        progreso = (completado / total) if total > 0 else 0.0

        nombre = "(obteniendo nombre…)"
        info = (t.get("bittorrent") or {}).get("info") or {}
        if info.get("name"):
            nombre = info["name"]
        elif t.get("files"):
            primero = t["files"][0].get("path", "")
            nombre = os.path.basename(primero) or nombre

        dlspeed = int(t.get("downloadSpeed", 0) or 0)
        eta = int((total - completado) / dlspeed) if dlspeed > 0 else -1

        return TorrentInfo(
            hash=t.get("gid", ""), name=nombre, progress=progreso,
            state=_ESTADO_ARIA2_A_INTERNO.get(t.get("status", ""), t.get("status", "")),
            dlspeed=dlspeed, size=total, eta=eta,
            upspeed=int(t.get("uploadSpeed", 0) or 0),
            peers=int(t.get("connections", 0) or 0),
        )

    def pausar(self, hash_: str):
        self._rpc_call("aria2.pause", [hash_])

    def reanudar(self, hash_: str):
        self._rpc_call("aria2.unpause", [hash_])

    def eliminar(self, hash_: str, borrar_archivos: bool = False):
        """
        Nota honesta: aria2 no borra los archivos ya descargados al quitar
        un torrent de la lista (borrar_archivos queda sin implementar por
        ahora) — solo deja de descargar/compartirlo. Si hace falta borrar
        también el contenido, se puede añadir mirando 'files' de
        aria2.tellStatus antes de eliminar, pero con torrents de varios
        archivos hay que hacerlo con cuidado para no dejar algo a medias.
        """
        self._rpc_call("aria2.remove", [hash_])
        self._rpc_call("aria2.removeDownloadResult", [hash_])

    def cerrar(self, on_wait=None):
        """
        Apaga aria2c limpiamente. Imprescindible llamarlo al cerrar la app,
        o el proceso se queda huérfano corriendo en segundo plano.

        on_wait: callback opcional invocado repetidamente mientras se
        espera a que el proceso termine (normalmente
        QApplication.processEvents, pasado desde la UI) -- sin esto, la
        espera bloquea el hilo de la interfaz entero. Con torrents activos
        pesando la RPC de aria2, ese bloqueo podía superar los segundos que
        tarda Windows en marcar la ventana como "no responde"; si el
        usuario forzaba el cierre en ese momento, aria2c.exe se quedaba sin
        llegar a apagarse -- exactamente el "se queda activo al cerrar"
        reportado. Ver core.recorder.Recorder.stop(), mismo patrón.
        """
        if self._proceso is None:
            return
        # Timeout corto a propósito: aria2 corre en el propio PC (loopback
        # HTTP), así que si está vivo responde en milisegundos. Los 5s por
        # defecto de _rpc_call tienen sentido para operaciones normales,
        # pero aquí solo alargarían la espera del cierre sin necesidad si
        # aria2 ya no responde.
        self._rpc_call("aria2.shutdown", timeout=1.5)

        deadline = time.monotonic() + 3
        while self._proceso.poll() is None and time.monotonic() < deadline:
            if on_wait:
                on_wait()
            time.sleep(0.05)

        if self._proceso.poll() is None:
            self._proceso.kill()
            try:
                self._proceso.wait(timeout=2)
            except subprocess.TimeoutExpired:
                log.warning("aria2c.exe no terminó ni siquiera tras kill()")
        self._proceso = None

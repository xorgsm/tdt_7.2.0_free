"""
Catálogo de podcasts vía RSS: añadir un feed por su URL, listar sus
episodios (título, fecha, duración si el feed la trae, y la URL directa
del audio) y descargarlos.

Mismo patrón de caché que core/epg.py (una copia en disco, refrescada
solo de vez en cuando) para no depender de la red cada vez que se abre
la pestaña de Podcasts, y mismo patrón de descarga en streaming que
core/downloader.ensure_yt_dlp() -- aquí no hace falta yt-dlp: el
enclosure de un item RSS ya es una URL de archivo directa, así que basta
con una descarga HTTP normal, sin extracción de por medio.

Coder By X@R
"""
import hashlib
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import List

import requests
from PySide6.QtCore import QThread, Signal

from core.config import get_app_data_dir
from core.logger import get_logger

log = get_logger(__name__)

FEEDS_FILE = "podcast_feeds.json"
CACHE_TTL_SECONDS = 3 * 3600
_NS_ITUNES = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}


@dataclass
class PodcastFeed:
    name: str
    url: str


@dataclass
class Episode:
    title: str
    audio_url: str
    published: str = ""
    description: str = ""
    duration: str = ""


# --------------------------------------------------------------------------
# Feeds suscritos
# --------------------------------------------------------------------------

def _feeds_path():
    return get_app_data_dir() / FEEDS_FILE


def load_feeds() -> List[PodcastFeed]:
    path = _feeds_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    resultado = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            resultado.append(PodcastFeed(**item))
        except TypeError:
            continue
    return resultado


def _save_feeds(feeds: List[PodcastFeed]) -> None:
    try:
        _feeds_path().write_text(
            json.dumps([asdict(f) for f in feeds], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def add_feed(name: str, url: str) -> List[PodcastFeed]:
    feeds = load_feeds()
    if not any(f.url == url for f in feeds):
        feeds.append(PodcastFeed(name=name or url, url=url))
        _save_feeds(feeds)
    return feeds


def remove_feed(url: str) -> List[PodcastFeed]:
    feeds = [f for f in load_feeds() if f.url != url]
    _save_feeds(feeds)
    return feeds


# --------------------------------------------------------------------------
# Episodios (parseo del RSS)
# --------------------------------------------------------------------------

def _cache_path_for(feed_url: str):
    slug = hashlib.md5(feed_url.encode("utf-8")).hexdigest()[:12]
    return get_app_data_dir() / "cache" / f"podcast_{slug}.json"


def _texto(elemento, tag: str, ns=None) -> str:
    hijo = elemento.find(tag, ns) if ns else elemento.find(tag)
    return (hijo.text or "").strip() if hijo is not None and hijo.text else ""


def fetch_episodes(feed_url: str, force_refresh: bool = False, limit: int = 60) -> List[Episode]:
    """Descarga y parsea el feed; si falla, cae a la última copia cacheada."""
    cache_path = _cache_path_for(feed_url)

    def _leer_cache():
        if not cache_path.exists():
            return []
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return [Episode(**e) for e in data]
        except (json.JSONDecodeError, OSError, TypeError):
            return []

    if not force_refresh and cache_path.exists():
        edad = time.time() - cache_path.stat().st_mtime
        if edad < CACHE_TTL_SECONDS:
            cacheado = _leer_cache()
            if cacheado:
                return cacheado

    try:
        resp = requests.get(feed_url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError):
        return _leer_cache()

    episodios = []
    for item in root.findall(".//item")[:limit]:
        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url", "") if enclosure is not None else ""
        if not audio_url:
            continue  # sin audio no hay nada que reproducir/descargar
        episodios.append(Episode(
            title=_texto(item, "title") or "(sin título)",
            audio_url=audio_url,
            published=_texto(item, "pubDate"),
            description=_texto(item, "description"),
            duration=_texto(item, "itunes:duration", _NS_ITUNES),
        ))

    if episodios:
        try:
            cache_path.write_text(
                json.dumps([asdict(e) for e in episodios], ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return episodios

    return _leer_cache()


# --------------------------------------------------------------------------
# Descarga de un episodio
# --------------------------------------------------------------------------

class EpisodeDownloadWorker(QThread):
    """
    Descarga en streaming el audio de un episodio a `dest_dir`. No usa
    yt-dlp (core.downloader.DownloadWorker): el enclosure del RSS ya es
    una URL de archivo directa, así que una descarga HTTP normal basta y
    evita arrastrar aquí toda la lógica de extracción/postproceso de vídeo
    que sí hace falta para el resto de descargas de la app.
    """
    progress = Signal(float, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, episode: Episode, dest_dir: str, parent=None):
        super().__init__(parent)
        self.episode = episode
        self.dest_dir = dest_dir
        self._cancelado = False

    def cancel(self):
        self._cancelado = True

    def run(self):
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
        except OSError as exc:
            self.failed.emit(f"No se pudo crear la carpeta de destino: {exc}")
            return

        nombre_seguro = re.sub(r'[\\/*?:"<>|]', "", self.episode.title).strip() or "episodio"
        ext = os.path.splitext(self.episode.audio_url.split("?")[0])[1] or ".mp3"
        destino = os.path.join(self.dest_dir, f"{nombre_seguro}{ext}")
        parcial = f"{destino}.part"

        try:
            peticion = urllib.request.Request(
                self.episode.audio_url, headers={"User-Agent": "TDT-Radio-VIP"}
            )
            with urllib.request.urlopen(peticion, timeout=20) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                bajado = 0
                with open(parcial, "wb") as fh:
                    while True:
                        if self._cancelado:
                            self.failed.emit("__cancelled__")
                            return
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        fh.write(chunk)
                        bajado += len(chunk)
                        if total:
                            self.progress.emit(bajado / total, f"Descargando… {bajado * 100 // total}%")
            os.replace(parcial, destino)
        except Exception as exc:
            log.exception("Fallo descargando episodio de podcast: %s", self.episode.audio_url)
            self.failed.emit(str(exc))
            return
        finally:
            try:
                if os.path.exists(parcial):
                    os.remove(parcial)
            except OSError:
                log.warning("No se pudo eliminar la descarga parcial %s", parcial, exc_info=True)

        self.finished_ok.emit(destino)

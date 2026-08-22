"""
Obtención y parseo de listas de canales de TDT en formato m3u/m3u8.

Fuente por defecto: listas públicas y gratuitas de iptv-org, mantenidas por
la comunidad: https://github.com/iptv-org/iptv — una por país.
"""
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from typing import List

import requests

from core.config import get_app_data_dir, get_profile_data_dir
from core.json_store import write_json_atomic

CUSTOM_FILE = "tv_channels_custom.json"
# Nombres de canales de la lista PÚBLICA (iptv-org/URL de país, no los
# personalizados) que el usuario ha pedido ocultar -- ver hide_channels()
# más abajo. A diferencia de tv_channels_custom.json, esto no guarda datos
# de ningún canal, solo su nombre: la lista pública se sigue descargando y
# cacheando entera como siempre, esto es un filtro que se aplica encima al
# combinarla con la personalizada (ver ui/main_window._on_tv_channels_loaded).
HIDDEN_FILE = "tv_channels_hidden.json"

IPTV_ORG_BASE = "https://iptv-org.github.io/iptv/countries"

EXTINF_RE = re.compile(
    r'#EXTINF:-?\d+(?P<attrs>(?:\s+[\w-]+="[^"]*")*)\s*,\s*(?P<name>.+)'
)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def playlist_url_for(country_code: str) -> str:
    """URL pública de iptv-org para la lista de un país (código ISO alfa-2)."""
    return f"{IPTV_ORG_BASE}/{(country_code or 'es').lower()}.m3u"


def _cache_path_for(playlist_url: str):
    """
    Un archivo de caché por URL (hash corto), no uno solo compartido.

    Con un único "tv_channels_cache.json" para todos los países, cambiar de
    país en Ajustes seguía mostrando la caché del país anterior hasta que
    tocaba "Actualizar canales". Cada URL (país, o una anulación manual de
    usuario avanzado) tiene ahora su propia caché independiente.
    """
    slug = hashlib.md5(playlist_url.encode("utf-8")).hexdigest()[:12]
    return get_app_data_dir() / "cache" / f"tv_channels_cache_{slug}.json"


@dataclass
class Channel:
    name: str
    url: str
    logo: str = ""
    group: str = ""
    tvg_id: str = ""


def dedupe_channels(channels: List[Channel]) -> List[Channel]:
    """
    Quita canales repetidos por nombre (sin distinguir mayúsculas ni
    espacios sobrantes), quedándose con la primera aparición. No es raro
    que una misma lista M3U pública traiga el mismo canal dos veces (varias
    URLs "de respaldo" bajo el mismo nombre), y tampoco que la lista del
    país por defecto y una lista personalizada importada compartan canales
    -- de ahí que esto se aplique tanto al final de parse_m3u() (dentro de
    una sola lista) como al combinar la lista del país con la personalizada
    (entre dos fuentes distintas).
    """
    vistos = set()
    resultado: List[Channel] = []
    for ch in channels:
        clave = ch.name.strip().casefold()
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(ch)
    return resultado


def parse_m3u(text: str) -> List[Channel]:
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    channels: List[Channel] = []
    pending: Channel | None = None
    for line in lines:
        if line.startswith("#EXTINF"):
            m = EXTINF_RE.match(line)
            if not m:
                pending = None
                continue
            attrs = dict(ATTR_RE.findall(m.group("attrs") or ""))
            pending = Channel(
                name=m.group("name").strip(),
                url="",
                logo=attrs.get("tvg-logo", ""),
                group=attrs.get("group-title", ""),
                tvg_id=attrs.get("tvg-id", ""),
            )
        elif line.startswith("#"):
            continue
        else:
            if pending is not None:
                pending.url = line
                channels.append(pending)
                pending = None
    return dedupe_channels(channels)


def fetch_tv_channels(playlist_url: str, force_refresh: bool = False) -> List[Channel]:
    """Descarga la lista de canales; si falla, usa la caché local en disco."""
    cache_path = _cache_path_for(playlist_url)

    cached: List[Channel] = []
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = [Channel(**c) for c in data]
        except (json.JSONDecodeError, OSError, TypeError):
            cached = []

    if not force_refresh and cached:
        return cached

    try:
        resp = requests.get(playlist_url, timeout=12)
        resp.raise_for_status()
        channels = parse_m3u(resp.text)
        if channels:
            try:
                write_json_atomic(cache_path, [asdict(c) for c in channels])
            except OSError:
                pass  # no poder cachear no invalida la lista ya descargada
            return channels
    except requests.RequestException:
        pass

    return cached


def _save_custom(channels: List[Channel]) -> None:
    """Punto único de guardado de la lista personalizada."""
    path = get_profile_data_dir() / CUSTOM_FILE
    try:
        write_json_atomic(path, [asdict(c) for c in channels])
    except OSError:
        pass


def load_custom_channels() -> List[Channel]:
    path = get_profile_data_dir() / CUSTOM_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        channels = [Channel(**c) for c in data]
    except (json.JSONDecodeError, OSError, TypeError):
        return []

    # Auto-reparación: si esta lista se guardó antes de que parse_m3u()
    # quitara duplicados (importar la misma lista dos veces, o importar una
    # que ya traía el mismo canal repetido, dejaba entradas duplicadas
    # guardadas en disco para siempre -- dedupe_channels() en el import
    # solo evita añadir MÁS duplicados a partir de ahora, no limpia los que
    # ya estaban). Si al desduplicar cambia algo, se guarda ya limpio de
    # una vez -- así no hace falta ninguna acción manual del usuario.
    limpios = dedupe_channels(channels)
    if len(limpios) != len(channels):
        _save_custom(limpios)
    return limpios


def add_custom_channel(channel: Channel) -> None:
    channels = load_custom_channels()
    channels.append(channel)
    _save_custom(channels)


def add_custom_channels(channels: List[Channel]) -> None:
    """
    Añade varios canales de golpe con una sola lectura y una sola escritura
    del archivo, en vez de una por canal (ver add_custom_channel). Pensada
    para "Importar lista M3U…": con listas de cientos o miles de canales,
    llamar a add_custom_channel() en bucle relee y reescribe el JSON entero
    en cada iteración, cada vez más grande — aquí se acumula en memoria y
    se guarda una única vez al final.
    """
    if not channels:
        return
    actuales = load_custom_channels()
    actuales.extend(channels)
    _save_custom(actuales)


def update_custom_channel(old_name: str, channel: Channel) -> None:
    _save_custom([channel if c.name == old_name else c for c in load_custom_channels()])


def remove_custom_channel(name: str) -> None:
    _save_custom([c for c in load_custom_channels() if c.name != name])


def remove_custom_channels(names) -> int:
    """
    Quita varios canales de golpe con una sola lectura y una sola escritura
    del archivo (ver add_custom_channels) -- pensada para el borrado múltiple
    del gestor de canales personalizados (ManageChannelsDialog), en vez de
    llamar a remove_custom_channel() en bucle, que releería y reescribiría
    el JSON entero por cada canal borrado. Devuelve cuántos se borraron de
    verdad (puede ser menos que len(names) si algún nombre ya no existía).
    """
    nombres = set(names)
    if not nombres:
        return 0
    actuales = load_custom_channels()
    restantes = [c for c in actuales if c.name not in nombres]
    borrados = len(actuales) - len(restantes)
    if borrados:
        _save_custom(restantes)
    return borrados


# ── Canales ocultos de la lista pública ─────────────────────────────────────
#
# Los personalizados (arriba) el usuario los añadió él mismo, así que
# borrarlos de verdad tiene sentido. Los de la lista pública (iptv-org o la
# URL de país que sea) se vuelven a descargar en cada "Actualizar canales",
# así que "borrarlos" no se sostendría -- volverían la próxima vez. En vez
# de eso se guarda solo el NOMBRE de los que no se quieren ver, y se filtran
# al combinar la lista pública con la personalizada. Reversible en cualquier
# momento desde ManageChannelsDialog ("Ocultados" -> Restaurar).

def _hidden_path():
    return get_profile_data_dir() / HIDDEN_FILE


def load_hidden_channel_names() -> set:
    path = _hidden_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError, TypeError):
        return set()


def _save_hidden(names: set) -> None:
    try:
        write_json_atomic(_hidden_path(), sorted(names))
    except OSError:
        pass


def hide_channels(names) -> int:
    """
    Añade nombres a la lista de ocultos. Devuelve cuántos son nuevos
    (nombres ya ocultos antes no cuentan). No comprueba que el nombre
    exista de verdad en ninguna lista pública -- solo guarda el filtro.
    """
    nuevos = set(names)
    if not nuevos:
        return 0
    actuales = load_hidden_channel_names()
    combinados = actuales | nuevos
    añadidos = len(combinados) - len(actuales)
    if añadidos:
        _save_hidden(combinados)
    return añadidos


def unhide_channels(names) -> int:
    """Quita nombres de la lista de ocultos (los vuelve a mostrar)."""
    quitar = set(names)
    if not quitar:
        return 0
    actuales = load_hidden_channel_names()
    restantes = actuales - quitar
    quitados = len(actuales) - len(restantes)
    if quitados:
        _save_hidden(restantes)
    return quitados


def filter_hidden(channels: List[Channel]) -> List[Channel]:
    """Quita de `channels` los que estén en la lista de ocultos."""
    ocultos = load_hidden_channel_names()
    if not ocultos:
        return channels
    return [c for c in channels if c.name not in ocultos]


# ── Fallos consecutivos por canal (aviso de auto-ocultar) ───────────────────
#
# PlaybackController cuenta cuántas veces seguidas falla un canal al
# reproducirse y, a partir de cierto número, ofrece ocultarlo (ver
# hide_channels() arriba) con un aviso no bloqueante en vez de asumir que
# es un fallo puntual de red. Se guarda por NOMBRE, no por URL: si cambia
# la URL de un canal personalizado es razonable que el contador arranque
# de cero. "Consecutivos" de verdad (no total histórico): cada vez que el
# canal responde bien se resetea, ver reset_channel_failures().

FAILCOUNT_FILE = "tv_channels_failcount.json"


def _failcount_path():
    return get_profile_data_dir() / FAILCOUNT_FILE


def _load_failcounts() -> dict:
    path = _failcount_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_failcounts(counts: dict) -> None:
    try:
        write_json_atomic(_failcount_path(), counts)
    except OSError:
        pass


def record_channel_failure(name: str) -> int:
    """Suma un fallo consecutivo para ese canal y devuelve el total acumulado."""
    if not name:
        return 0
    counts = _load_failcounts()
    counts[name] = counts.get(name, 0) + 1
    _save_failcounts(counts)
    return counts[name]


def reset_channel_failures(name: str) -> None:
    """Se llama cuando el canal responde bien -- limpia su contador si tenía alguno."""
    if not name:
        return
    counts = _load_failcounts()
    if name in counts:
        del counts[name]
        _save_failcounts(counts)

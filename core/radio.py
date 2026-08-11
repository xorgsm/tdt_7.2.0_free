"""
Cliente para la API pública y gratuita Radio-Browser (radio-browser.info).
No requiere clave de API. https://api.radio-browser.info/
"""
import json
from dataclasses import dataclass, asdict
from typing import List

import requests

from core.config import get_app_data_dir, get_profile_data_dir

CUSTOM_FILE = "radio_stations_custom.json"
# Emisoras de la lista PÚBLICA (Radio-Browser) ocultas a mano por el
# usuario -- ver core.channels.HIDDEN_FILE, misma idea aplicada a radio.
HIDDEN_FILE = "radio_stations_hidden.json"
# Radio-Browser es una red de servidores espejo: si solo se usa uno y ese cae,
# la radio deja de funcionar entera. Se prueban en orden hasta que uno responda.
API_MIRRORS = (
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
)
USER_AGENT = "TDTRadioVIP/2.0 (CoderByXR)"


@dataclass
class Station:
    name: str
    url: str
    favicon: str = ""
    tags: str = ""
    bitrate: int = 0
    country: str = ""


def _cache_path_for(country_code: str):
    """Una caché por país (código ISO), no una sola compartida entre todos."""
    slug = (country_code or "ES").upper()
    return get_app_data_dir() / "cache" / f"radio_stations_cache_{slug}.json"


def fetch_radio_stations(country_code: str = "ES", limit: int = 250, force_refresh: bool = False) -> List[Station]:
    cache_path = _cache_path_for(country_code)

    cached: List[Station] = []
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = [Station(**s) for s in data]
        except (json.JSONDecodeError, OSError, TypeError):
            cached = []

    if not force_refresh and cached:
        return cached

    code = (country_code or "ES").upper()
    for base in API_MIRRORS:
        try:
            resp = requests.get(
                # bycountrycodeexact (código ISO) en vez de bycountry (nombre
                # en inglés): evita fallos por variantes de escritura del
                # nombre del país y es el mismo código que ya usamos para la
                # lista de TV de iptv-org, así que solo hace falta mantener
                # un código por país en toda la app.
                f"{base}/json/stations/bycountrycodeexact/{code}",
                params={
                    "hidebroken": "true",
                    "order": "clickcount",
                    "reverse": "true",
                    "limit": limit,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=12,
            )
            resp.raise_for_status()
            raw = resp.json()
        except (requests.RequestException, ValueError):
            continue  # este espejo falla: probar el siguiente

        stations = [
            Station(
                name=(s.get("name") or "").strip() or "Sin nombre",
                url=s.get("url_resolved") or s.get("url", ""),
                favicon=s.get("favicon", ""),
                tags=s.get("tags", ""),
                bitrate=s.get("bitrate", 0) or 0,
                country=s.get("country", ""),
            )
            for s in raw
            if s.get("url_resolved") or s.get("url")
        ]
        if stations:
            try:
                cache_path.write_text(
                    json.dumps([asdict(s) for s in stations], ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass  # no poder cachear no invalida los datos ya obtenidos
            return stations

    return cached


def _save_custom(stations: List[Station]) -> None:
    """Punto único de guardado de la lista personalizada."""
    path = get_profile_data_dir() / CUSTOM_FILE
    try:
        path.write_text(
            json.dumps([asdict(s) for s in stations], ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def load_custom_stations() -> List[Station]:
    path = get_profile_data_dir() / CUSTOM_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Station(**s) for s in data]
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def add_custom_station(station: Station) -> None:
    stations = load_custom_stations()
    stations.append(station)
    _save_custom(stations)


def add_custom_stations(stations: List[Station]) -> None:
    """
    Añade varias emisoras de golpe con una sola lectura y una sola escritura
    del archivo, en vez de una por emisora (ver add_custom_station). Mismo
    motivo que core.channels.add_custom_channels: evita releer/reescribir
    el JSON entero por cada elemento al importar una lista M3U grande.
    """
    if not stations:
        return
    actuales = load_custom_stations()
    actuales.extend(stations)
    _save_custom(actuales)


def update_custom_station(old_name: str, station: Station) -> None:
    _save_custom([station if s.name == old_name else s for s in load_custom_stations()])


def remove_custom_station(name: str) -> None:
    _save_custom([s for s in load_custom_stations() if s.name != name])


def remove_custom_stations(names) -> int:
    """
    Quita varias emisoras de golpe con una sola lectura y una sola escritura
    (ver add_custom_stations / core.channels.remove_custom_channels, mismo
    motivo). Devuelve cuántas se borraron de verdad.
    """
    nombres = set(names)
    if not nombres:
        return 0
    actuales = load_custom_stations()
    restantes = [s for s in actuales if s.name not in nombres]
    borradas = len(actuales) - len(restantes)
    if borradas:
        _save_custom(restantes)
    return borradas


# ── Emisoras ocultas de la lista pública ────────────────────────────────────
# Ver core.channels: misma idea, solo se guarda el nombre y se filtra al
# combinar la lista pública (Radio-Browser) con la personalizada.

def _hidden_path():
    return get_profile_data_dir() / HIDDEN_FILE


def load_hidden_station_names() -> set:
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
        _hidden_path().write_text(
            json.dumps(sorted(names), ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def hide_stations(names) -> int:
    nuevos = set(names)
    if not nuevos:
        return 0
    actuales = load_hidden_station_names()
    combinados = actuales | nuevos
    añadidos = len(combinados) - len(actuales)
    if añadidos:
        _save_hidden(combinados)
    return añadidos


def unhide_stations(names) -> int:
    quitar = set(names)
    if not quitar:
        return 0
    actuales = load_hidden_station_names()
    restantes = actuales - quitar
    quitados = len(actuales) - len(restantes)
    if quitados:
        _save_hidden(restantes)
    return quitados


def filter_hidden(stations: List[Station]) -> List[Station]:
    ocultas = load_hidden_station_names()
    if not ocultas:
        return stations
    return [s for s in stations if s.name not in ocultas]


# ── Fallos consecutivos por emisora (aviso de auto-ocultar) ─────────────────
# Ver core.channels: misma idea, misma lógica, aplicada a radio.

FAILCOUNT_FILE = "radio_stations_failcount.json"


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
        _failcount_path().write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def record_channel_failure(name: str) -> int:
    """Suma un fallo consecutivo para esa emisora y devuelve el total acumulado."""
    if not name:
        return 0
    counts = _load_failcounts()
    counts[name] = counts.get(name, 0) + 1
    _save_failcounts(counts)
    return counts[name]


def reset_channel_failures(name: str) -> None:
    """Se llama cuando la emisora responde bien -- limpia su contador si tenía alguno."""
    if not name:
        return
    counts = _load_failcounts()
    if name in counts:
        del counts[name]
        _save_failcounts(counts)

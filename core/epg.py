"""
Guía de programación (EPG) en formato XMLTV.

Es OPCIONAL: la app funciona sin ella. Las URLs de EPG gratuitas de
terceros cambian con el tiempo, así que se configura manualmente desde
Configuración > Preferencias con la URL XMLTV que prefieras.

Nota importante sobre el emparejamiento de canales:
Cada fuente EPG usa su propia convención de identificadores de canal, y
casi nunca coincide con el tvg-id que trae la lista M3U de canales. Por
ejemplo, la lista de iptv-org (fuente de TV por defecto de la app) usa
tvg-id="La1.es@SD", mientras que una guía EPG típica de terceros usa
id="la 1.es" o id="La 1 HD" con <display-name>La 1</display-name>. Si se
compara tal cual con "==" (como hacía esta app antes), la guía nunca
cruza ni un solo canal aunque la URL esté viva y con datos frescos —
justo el "la guía nunca funciona" que se reportó. channel_key() normaliza
ambos lados (tvg-id de la lista Y id/display-name del XMLTV) a una misma
forma comparable para que el emparejamiento funcione entre fuentes
distintas.
"""
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from core.config import get_app_data_dir

CACHE_FILE = "epg_cache.json"
CACHE_TTL_SECONDS = 6 * 3600

# "@SD", "@HD", "@Originals"... -- sufijo de calidad/variante que iptv-org
# añade a sus tvg-id, y que ninguna fuente EPG externa usa jamás.
_SUFIJO_CALIDAD_RE = re.compile(r"@[A-Za-z0-9]+$")


def channel_key(identificador: str) -> str:
    """
    Normaliza un tvg-id (de la lista M3U) o un id/display-name de canal
    (de un XMLTV) a una clave comparable entre fuentes: quita el sufijo
    de calidad de iptv-org si lo trae, quita acentos, pasa a minúsculas,
    quita el sufijo de país ".es" si va al final, y se queda solo con
    letras/números (fuera espacios, puntos, guiones...).

    Ver la nota del docstring del módulo para el porqué. Ejemplos:
        "La1.es@SD"    -> "la1"
        "la 1.es"      -> "la1"
        "La 1 HD"      -> "la1hd"   (display-name "La 1" -> "la1" aparte)
        "antena 3.es"  -> "antena3"
    """
    if not identificador:
        return ""
    texto = _SUFIJO_CALIDAD_RE.sub("", identificador)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"\.es$", "", texto)
    return re.sub(r"[^a-z0-9]", "", texto)


@dataclass
class Programme:
    channel_id: str
    title: str
    start: str
    stop: str
    description: str = ""


def _parse_xmltv_time(value: str) -> Optional[datetime]:
    value = value.strip().split(" ")[0]
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None


# Alias público: la parrilla de programación (ui/epg_dialog.py) necesita
# parsear horas de inicio/fin igual que este módulo, y usar un nombre con
# guion bajo de otro módulo no es buena práctica aunque Python lo permita.
parse_xmltv_time = _parse_xmltv_time


def fetch_epg(epg_url: str, force_refresh: bool = False) -> Dict[str, List[Programme]]:
    if not epg_url:
        return {}

    cache_path = get_app_data_dir() / "cache" / CACHE_FILE

    def _read_cache():
        if not cache_path.exists():
            return {}
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            return {cid: [Programme(**p) for p in progs] for cid, progs in raw.items()}
        except (json.JSONDecodeError, OSError, TypeError):
            return {}

    if not force_refresh and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            cached = _read_cache()
            if cached:
                return cached

    try:
        resp = requests.get(epg_url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError):
        return _read_cache()

    # Antes de leer los <programme>, se recogen las claves normalizadas de
    # cada <channel> -- su id Y todos sus <display-name> (algunas guías,
    # como EPG_dobleM, listan media docena de variantes del mismo canal:
    # "La 1", "La 1 HD", "La 1 SD"...). Un <programme channel="X"> se
    # registra bajo TODAS esas claves, para que un tvg-id de la lista M3U
    # que coincida con cualquiera de ellas (el id crudo o cualquier
    # display-name) encuentre la programación igualmente.
    claves_por_id_crudo: Dict[str, set] = {}
    for ch_el in root.findall("channel"):
        raw_id = ch_el.get("id", "")
        if not raw_id:
            continue
        candidatos = {raw_id}
        for nombre_el in ch_el.findall("display-name"):
            if nombre_el.text:
                candidatos.add(nombre_el.text)
        claves = {channel_key(c) for c in candidatos}
        claves.discard("")
        if claves:
            claves_por_id_crudo[raw_id] = claves

    guide: Dict[str, List[Programme]] = {}
    for prog in root.findall("programme"):
        channel_id = prog.get("channel", "")
        title_el = prog.find("title")
        desc_el = prog.find("desc")
        programme = Programme(
            channel_id=channel_id,
            # Ojo: un <title></title> vacío devuelve None, no "". Ese None
            # llegaría hasta la interfaz y rompería al pintar el texto.
            title=(title_el.text or "") if title_el is not None else "",
            start=prog.get("start", ""),
            stop=prog.get("stop", ""),
            description=(desc_el.text or "") if desc_el is not None else "",
        )
        claves = claves_por_id_crudo.get(channel_id) or {channel_key(channel_id)}
        for clave in claves:
            if clave:
                guide.setdefault(clave, []).append(programme)

    if guide:
        try:
            cache_path.write_text(
                json.dumps(
                    {cid: [asdict(p) for p in progs] for cid, progs in guide.items()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            # Sin permisos o disco lleno: no es motivo para tirar la guía ya
            # descargada, simplemente esta vez no se cachea.
            pass
    return guide or _read_cache()


def get_now_next(
    guide: Dict[str, List[Programme]], channel_id: str
) -> Tuple[Optional[Programme], Optional[Programme]]:
    # guide está indexado por channel_key(), no por el tvg-id/id crudo --
    # ver el docstring del módulo y channel_key() para el porqué.
    programmes = guide.get(channel_key(channel_id), [])
    now = datetime.now()
    current = None
    upcoming = None
    for prog in sorted(programmes, key=lambda p: p.start):
        start = _parse_xmltv_time(prog.start)
        stop = _parse_xmltv_time(prog.stop)
        if start and stop and start <= now <= stop:
            current = prog
        elif start and start > now and upcoming is None:
            upcoming = prog
    return current, upcoming

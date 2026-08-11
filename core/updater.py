"""
Comprobación de actualizaciones "de solo consulta": ni descarga ni
reemplaza el .exe en marcha (eso es tarea del instalador de Inno Setup,
ver TDTRadioVIP_Setup.iss) -- esto solo mira si hay una versión más
reciente publicada y, si la hay, deja que el usuario decida abrir la
página de descarga a mano. Mismo patrón de "URL opcional, vacía por
defecto = desactivado" que core/epg.py con epg_url.

Formato esperado en update_check_url: un JSON tipo
    {"version": "6.5.0", "url": "https://.../descargas"}

Coder By X@R
"""
import re
from typing import Optional

import requests

from core.config import APP_VERSION
from core.logger import get_logger

log = get_logger(__name__)


def _version_tuple(texto: str) -> tuple:
    """
    '6.10.2' -> (6, 10, 2). Componentes no numéricos (sufijos tipo
    '6.4.0-beta') se ignoran en vez de reventar la comparación.
    """
    partes = re.findall(r"\d+", texto or "")
    return tuple(int(p) for p in partes) if partes else (0,)


def check_for_update(update_check_url: str, current_version: str = APP_VERSION) -> Optional[dict]:
    """
    Devuelve el JSON remoto ({"version": ..., "url": ...}) si describe una
    versión más nueva que la actual, o None si la URL está vacía (función
    desactivada), si no hay red, si el JSON es inválido, o si ya se tiene
    la última versión. Nunca lanza -- se llama desde un hilo de fondo (ver
    ui/fetch_worker.FetchWorker) y un fallo de red no debe ser más que
    "no hay actualización que mostrar".
    """
    if not update_check_url:
        return None
    try:
        resp = requests.get(update_check_url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("No se pudo comprobar actualizaciones en %s", update_check_url, exc_info=True)
        return None

    if not isinstance(data, dict):
        return None
    version_remota = data.get("version", "")
    if not version_remota:
        return None

    if _version_tuple(version_remota) > _version_tuple(current_version):
        return data
    return None

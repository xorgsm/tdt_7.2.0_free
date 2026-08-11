"""
Grabaciones programadas desde la guía EPG ("grabar este programa").

Mismo patrón que core/epg_reminders.py: una lista de pendientes persistida
en disco (sobrevive a cerrar y reabrir la app), comprobada periódicamente
por un QTimer en MainWindow. Este módulo NO depende de PySide6 ni toca
Recorder directamente -- solo lleva la contabilidad de qué grabación toca
arrancar o parar ahora mismo; quien llama (ui/main_window.py) es quien de
verdad arranca/para core.recorder.Recorder y actualiza la interfaz.

Ciclo de vida de una ScheduledRecording:
    pending   -> (llega la hora de inicio) -> recording
    recording -> (llega la hora de fin, o el usuario para a mano)   -> se borra (mark_done)
    pending/recording -> (algo falla al arrancar, o se llegó demasiado
                           tarde al inicio) -> error (se deja visible en
                           vez de borrarla en silencio, hasta que algo la
                           quite explícitamente)

Coder By X@R
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import List

from core.config import get_profile_data_dir

SCHEDULE_FILE = "epg_recordings.json"

# Si la app estuvo cerrada y se reabre pasado este margen desde el inicio
# del programa, ya no tiene sentido arrancar una grabación a la que le
# faltaría el principio entero -- se descarta en vez de grabar solo el
# final. Mismo margen que epg_reminders.MARGEN_TOLERANCIA por consistencia.
MARGEN_INICIO = timedelta(minutes=10)


@dataclass
class ScheduledRecording:
    tvg_id: str
    channel_name: str
    channel_url: str
    title: str
    start: str  # formato XMLTV: YYYYMMDDHHMMSS
    stop: str
    status: str = "pending"  # pending | recording | error


def _path():
    return get_profile_data_dir() / SCHEDULE_FILE


def load_scheduled() -> List[ScheduledRecording]:
    path = _path()
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
            resultado.append(ScheduledRecording(**item))
        except TypeError:
            continue  # entrada con campos que no encajan; se descarta sola
    return resultado


def _save(items: List[ScheduledRecording]) -> None:
    try:
        _path().write_text(
            json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _es_la_misma(r: ScheduledRecording, tvg_id: str, title: str, start: str) -> bool:
    return r.tvg_id == tvg_id and r.title == title and r.start == start


def has_scheduled(tvg_id: str, title: str, start: str) -> bool:
    return any(_es_la_misma(r, tvg_id, title, start) for r in load_scheduled())


def add_scheduled(rec: ScheduledRecording) -> List[ScheduledRecording]:
    """Añade una grabación programada si no existía ya una igual (mismo
    canal+programa+hora de inicio)."""
    items = load_scheduled()
    if not any(_es_la_misma(r, rec.tvg_id, rec.title, rec.start) for r in items):
        items.append(rec)
        _save(items)
    return items


def remove_scheduled(tvg_id: str, title: str, start: str) -> List[ScheduledRecording]:
    items = [r for r in load_scheduled() if not _es_la_misma(r, tvg_id, title, start)]
    _save(items)
    return items


def check_starts_due(parse_time_fn) -> List[ScheduledRecording]:
    """
    Devuelve las grabaciones "pending" cuya hora de inicio ya ha llegado
    (con margen de tolerancia hacia atrás -- ver MARGEN_INICIO) y las deja
    marcadas como "recording" en disco. Quien llama es responsable de
    arrancar Recorder.start() de verdad para cada una devuelta; si falla,
    debe llamar a mark_error() para no dejarla colgada en "recording" para
    siempre sin que nada la esté grabando de verdad.

    Las que llevan demasiado tiempo pendientes (se pasó de largo el margen
    de inicio -- típicamente la app estuvo cerrada) se marcan "error" en
    vez de arrancarlas ya mediadas: grabar solo el final de un programa no
    sirve de mucho y confundiría más que ayudar.
    """
    ahora = datetime.now()
    items = load_scheduled()
    listas = []
    cambiado = False
    for r in items:
        if r.status != "pending":
            continue
        inicio = parse_time_fn(r.start)
        if inicio is None:
            continue  # hora corrupta; se ignora en vez de arrancar algo mal
        if inicio <= ahora <= inicio + MARGEN_INICIO:
            r.status = "recording"
            cambiado = True
            listas.append(r)
        elif inicio > ahora:
            continue  # todavía no toca
        else:
            r.status = "error"
            cambiado = True
    if cambiado:
        _save(items)
    return listas


def check_stops_due(parse_time_fn) -> List[ScheduledRecording]:
    """
    Devuelve las grabaciones "recording" cuya hora de fin ya ha llegado --
    quien llama debe parar Recorder de verdad para cada una y después
    llamar a mark_done() (grabación cerrada con normalidad) o mark_error()
    (algo fue mal al pararla). Una hora de fin corrupta se trata como "ya
    tocaba pararla" en vez de dejarla grabando para siempre sin control.
    """
    ahora = datetime.now()
    items = load_scheduled()
    resultado = []
    for r in items:
        if r.status != "recording":
            continue
        fin = parse_time_fn(r.stop)
        if fin is None or fin <= ahora:
            resultado.append(r)
    return resultado


def mark_done(tvg_id: str, title: str, start: str) -> None:
    """Grabación terminada con normalidad: se quita de la lista de
    pendientes/activas (el archivo .mp4 ya vive en la carpeta de
    grabaciones, esto solo limpia la programación en sí)."""
    remove_scheduled(tvg_id, title, start)


def mark_error(tvg_id: str, title: str, start: str) -> None:
    """Deja la entrada visible como fallida en vez de borrarla en
    silencio, para que quien revise la parrilla vea que algo no salió
    bien (ver EpgDialog: una entrada 'error' se puede quitar a mano igual
    que una pendiente)."""
    items = load_scheduled()
    for r in items:
        if _es_la_misma(r, tvg_id, title, start):
            r.status = "error"
    _save(items)

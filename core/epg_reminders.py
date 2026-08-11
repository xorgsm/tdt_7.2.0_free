"""
Avisos de "empieza ahora" para programas de la parrilla EPG.

Se guarda una lista de avisos pendientes (canal, programa, hora de inicio)
en disco, para que sobrevivan a cerrar y volver a abrir la app. Un aviso
"toca" cuando la hora actual ya pasó su hora de inicio (con margen de
tolerancia hacia atrás, por si la app estaba cerrada justo en ese momento).

Coder By X@R
"""
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List

from core.config import get_app_data_dir

REMINDERS_FILE = "epg_reminders.json"

# Si la app estuvo cerrada y se reabre pasada esta cantidad de tiempo desde
# el inicio del programa, ya no tiene sentido avisar — se descarta en vez
# de lanzar un aviso de algo que empezó hace horas.
MARGEN_TOLERANCIA = timedelta(minutes=15)


@dataclass
class Reminder:
    tvg_id: str
    channel_name: str
    title: str
    start: str  # formato XMLTV: YYYYMMDDHHMMSS


def _path():
    return get_app_data_dir() / REMINDERS_FILE


def load_reminders() -> List[Reminder]:
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
            resultado.append(Reminder(**item))
        except TypeError:
            continue  # entrada con campos que no encajan; se descarta sola
    return resultado


def _save(reminders: List[Reminder]) -> None:
    try:
        _path().write_text(
            json.dumps([asdict(r) for r in reminders], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def add_reminder(reminder: Reminder) -> List[Reminder]:
    """Añade un aviso si no existía ya uno igual (mismo canal+programa+hora)."""
    reminders = load_reminders()
    ya_existe = any(
        r.tvg_id == reminder.tvg_id and r.title == reminder.title and r.start == reminder.start
        for r in reminders
    )
    if not ya_existe:
        reminders.append(reminder)
        _save(reminders)
    return reminders


def remove_reminder(tvg_id: str, title: str, start: str) -> List[Reminder]:
    reminders = [
        r for r in load_reminders()
        if not (r.tvg_id == tvg_id and r.title == title and r.start == start)
    ]
    _save(reminders)
    return reminders


def has_reminder(tvg_id: str, title: str, start: str) -> bool:
    return any(
        r.tvg_id == tvg_id and r.title == title and r.start == start
        for r in load_reminders()
    )


def check_due(parse_time_fn) -> List[Reminder]:
    """
    Devuelve los avisos cuya hora de inicio ya llegó (y no ha pasado tanto
    tiempo como para que ya no tenga sentido avisar), y los quita de la
    lista de pendientes — cada aviso solo se dispara una vez.

    parse_time_fn: función para convertir el string de hora XMLTV a
    datetime (se reutiliza core.epg.parse_xmltv_time, pasada como parámetro
    en vez de importada aquí, para no crear una dependencia circular entre
    core/epg.py y core/epg_reminders.py).
    """
    ahora = datetime.now()
    pendientes = load_reminders()
    disparados = []
    quedan = []

    for r in pendientes:
        inicio = parse_time_fn(r.start)
        if inicio is None:
            continue  # hora corrupta; se descarta en vez de avisar mal
        if inicio <= ahora <= inicio + MARGEN_TOLERANCIA:
            disparados.append(r)
        elif inicio > ahora:
            quedan.append(r)  # todavía no toca, se mantiene pendiente
        # si inicio + MARGEN_TOLERANCIA < ahora: ya pasó de largo, se descarta

    if disparados:
        _save(quedan)
    return disparados

"""
Historial de lo último reproducido.

Cada entrada es un diccionario con: type ('tv' o 'radio'), name, url,
timestamp (texto ya formateado, que la interfaz muestra como subtítulo) y
play_count (veces que se ha reproducido ese canal/emisora -- ver
top_played(), usado por ui/stats_dialog.py).
"""
import json
from datetime import datetime
from typing import List

from core.config import get_profile_data_dir
from core.json_store import write_json_atomic

HISTORY_FILE = "history.json"
MAX_ENTRIES = 100


def _path():
    return get_profile_data_dir() / HISTORY_FILE


def load_history() -> List[dict]:
    """Devuelve el historial guardado, del más reciente al más antiguo."""
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [
        e for e in data
        if isinstance(e, dict) and e.get("type") and e.get("name")
    ]


def _save(history: List[dict]) -> None:
    try:
        write_json_atomic(_path(), history, indent=2)
    except OSError:
        pass


def add_entry(item_type: str, name: str, url: str = "") -> List[dict]:
    """
    Registra una reproducción al principio del historial y devuelve la lista
    actualizada. Si ese canal ya estaba, se mueve arriba en vez de duplicarse,
    y se conserva (incrementado) su play_count en vez de reiniciarlo -- así
    top_played() puede saber qué se reproduce más, no solo qué se reprodujo
    la última vez.
    """
    history = load_history()
    if not item_type or not name:
        return history

    previo = next(
        (e for e in history if e.get("type") == item_type and e.get("name") == name),
        None,
    )
    play_count = (previo.get("play_count", 1) if previo else 0) + 1

    history = [
        e for e in history
        if not (e.get("type") == item_type and e.get("name") == name)
    ]
    history.insert(0, {
        "type": item_type,
        "name": name,
        "url": url or "",
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "play_count": play_count,
    })

    # Se recorta para que el archivo no crezca indefinidamente con el zapeo.
    history = history[:MAX_ENTRIES]
    _save(history)
    return history


def clear_history() -> List[dict]:
    _save([])
    return []


def top_played(history: List[dict] = None, limit: int = 10) -> List[dict]:
    """
    Devuelve las entradas más reproducidas (por play_count, de mayor a
    menor), para ui/stats_dialog.py. Las entradas antiguas sin play_count
    (historiales guardados antes de la 6.4) cuentan como 1 reproducción en
    vez de romper el orden.
    """
    if history is None:
        history = load_history()
    ordenado = sorted(history, key=lambda e: e.get("play_count", 1), reverse=True)
    return ordenado[:limit]

"""
Historial persistente de torrents completados.

libtorrent (igual que aria2 antes) no guarda un historial propio en disco
más allá de lo que dura el proceso corriendo — al cerrar la app, se
perdería la lista de "Completados" si no se guardara aparte. Mismo patrón
que core/history.py (canales/radio), pero para descargas de torrents.

Coder By X@R
"""
import json
from datetime import datetime
from typing import List

from core.config import get_profile_data_dir

TORRENT_HISTORY_FILE = "torrent_history.json"
MAX_ENTRIES = 200


def _path():
    return get_profile_data_dir() / TORRENT_HISTORY_FILE


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
        if isinstance(e, dict) and e.get("name") and e.get("path")
    ]


def _save(history: List[dict]) -> None:
    try:
        _path().write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def add_entry(name: str, path: str, size: int = 0) -> List[dict]:
    """
    Registra un torrent completado al principio del historial. Si ese
    mismo nombre+ruta ya estaba (p. ej. al reabrir la app y el motor de
    torrents lo reporta de nuevo como completo), se mueve arriba en vez de
    duplicarse.
    """
    history = load_history()
    if not name or not path:
        return history

    history = [e for e in history if not (e.get("name") == name and e.get("path") == path)]
    history.insert(0, {
        "name": name,
        "path": path,
        "size": size,
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })

    history = history[:MAX_ENTRIES]
    _save(history)
    return history


def has_entry(name: str, path: str) -> bool:
    return any(e.get("name") == name and e.get("path") == path for e in load_history())


def remove_entry(name: str, path: str) -> List[dict]:
    """Quita una entrada del historial (botón "Quitar" de la pestaña
    Torrents sobre un torrent ya completado) -- no borra el archivo en
    disco, solo deja de aparecer en la lista de completados."""
    history = [e for e in load_history() if not (e.get("name") == name and e.get("path") == path)]
    _save(history)
    return history


def clear_history() -> List[dict]:
    _save([])
    return []

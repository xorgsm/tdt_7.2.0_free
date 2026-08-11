"""
Gestión de canales y emisoras marcados como favoritos.

Se guardan en un JSON dentro de la carpeta de datos de la aplicación.
Cada favorito es un diccionario con: type ('tv' o 'radio'), name, url, logo
y folder (carpeta del usuario, vacío = sin carpeta / "General").
"""
import json
from typing import List, Optional

from core.config import get_profile_data_dir

FAVORITES_FILE = "favorites.json"


def _path():
    return get_profile_data_dir() / FAVORITES_FILE


def load_favorites() -> List[dict]:
    """Devuelve la lista de favoritos guardada, o vacía si no hay o está dañada."""
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    # Descarta entradas malformadas para que un archivo corrupto no tumbe la app.
    return [
        f for f in data
        if isinstance(f, dict) and f.get("type") and f.get("name")
    ]


def _save(favorites: List[dict]) -> None:
    try:
        _path().write_text(
            json.dumps(favorites, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # sin permisos o disco lleno: no es motivo para romper la sesión


def is_favorite(favorites: List[dict], item_type: str, name: str) -> bool:
    if not item_type or not name:
        return False
    return any(f.get("type") == item_type and f.get("name") == name for f in favorites)


def toggle_favorite(item_type: str, name: str, url: str = "", logo: str = "", folder: str = "") -> List[dict]:
    """
    Añade el elemento a favoritos si no estaba, o lo quita si ya estaba.
    Devuelve SIEMPRE la lista actualizada y la deja guardada en disco.
    """
    favorites = load_favorites()
    if not item_type or not name:
        return favorites

    restantes = [
        f for f in favorites
        if not (f.get("type") == item_type and f.get("name") == name)
    ]

    if len(restantes) != len(favorites):
        # Estaba: se ha quitado.
        _save(restantes)
        return restantes

    # No estaba: se añade al principio.
    favorites.insert(0, {
        "type": item_type,
        "name": name,
        "url": url or "",
        "logo": logo or "",
        "folder": folder or "",
    })
    _save(favorites)
    return favorites


def remove_favorite(item_type: str, name: str) -> List[dict]:
    """Quita un favorito sin alternar (útil al borrar un canal personalizado)."""
    favorites = [
        f for f in load_favorites()
        if not (f.get("type") == item_type and f.get("name") == name)
    ]
    _save(favorites)
    return favorites


# ---------- carpetas ----------

def get_folders(favorites: Optional[List[dict]] = None) -> List[str]:
    """Nombres de carpeta en uso (sin contar "sin carpeta"), ordenados."""
    favs = favorites if favorites is not None else load_favorites()
    return sorted({f.get("folder", "") for f in favs if f.get("folder")})


def set_favorite_folder(item_type: str, name: str, folder: str) -> List[dict]:
    """Asigna (o quita, con folder='') la carpeta de un favorito ya existente."""
    favorites = load_favorites()
    for f in favorites:
        if f.get("type") == item_type and f.get("name") == name:
            f["folder"] = folder or ""
            break
    _save(favorites)
    return favorites


def rename_folder(old_name: str, new_name: str) -> List[dict]:
    favorites = load_favorites()
    for f in favorites:
        if f.get("folder") == old_name:
            f["folder"] = new_name
    _save(favorites)
    return favorites


def reorder(favorites: List[dict]) -> List[dict]:
    """
    Persiste 'favorites' tal cual, ya reordenado por quien llama (p. ej.
    tras arrastrar filas en la pestaña de Favoritos de la interfaz). No
    valida ni completa campos -- para eso está toggle_favorite().
    """
    _save(favorites)
    return favorites


def delete_folder(folder: str) -> List[dict]:
    """Los favoritos de esa carpeta no se borran, solo pasan a 'sin carpeta'."""
    favorites = load_favorites()
    for f in favorites:
        if f.get("folder") == folder:
            f["folder"] = ""
    _save(favorites)
    return favorites

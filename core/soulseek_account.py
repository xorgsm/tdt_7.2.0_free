"""
Cuenta de Soulseek del perfil activo (usuario/contraseña de la red).
Igual que favorites.json/history.json: un JSON pequeño dentro de la
carpeta de datos del PERFIL (get_profile_data_dir()), no de la
instalación -- cada perfil de la app tiene su propia cuenta Soulseek,
igual que ya tiene sus propios favoritos.

Sin cifrado: mismo nivel de protección que el resto de datos de perfil
ya existentes en el proyecto, no es una regresión.

Coder By X@R
"""
from pathlib import Path
from typing import Optional

from core.config import get_profile_data_dir
from core.json_store import read_json, write_json_atomic

ACCOUNT_FILE = "soulseek_account.json"


def _path() -> Path:
    return get_profile_data_dir() / ACCOUNT_FILE


def load_account() -> Optional[dict]:
    """Devuelve {"username", "password"} del perfil activo, o None si no
    hay cuenta guardada o el archivo está corrupto/incompleto."""
    data = read_json(_path(), None)
    if not isinstance(data, dict):
        return None
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return None
    return {"username": username, "password": password}


def save_account(username: str, password: str) -> None:
    write_json_atomic(_path(), {"username": username, "password": password}, indent=2)

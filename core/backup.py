"""
Copia de seguridad de los datos del usuario en un solo archivo.

Reúne en un único JSON todo lo que vive normalmente repartido en varios
archivos dentro de %APPDATA%\\CoderByXR\\TDTRadioVIP\\: ajustes (país,
EPG, carpeta de grabaciones...), favoritos, historial, y los canales o
emisoras que el usuario haya añadido a mano. Útil sobre todo al cambiar de
PC — como pasó justo antes de construir esto — para no tener que rehacer
todo eso desde cero.

Coder By X@R
"""
import json
from datetime import datetime
from pathlib import Path

from core.config import get_app_data_dir, get_profile_data_dir, APP_VERSION
from core.json_store import replace_json_files_atomically, write_json_atomic

BACKUP_FORMAT_VERSION = 1

# Nombre de archivo -> clave bajo la que se guarda dentro del backup.
# settings.json es de la instalación entera (no cambia con el perfil);
# el resto son datos "de quién los usa" y viven en la carpeta del perfil
# activo (ver core.config.get_profile_data_dir) -- así, exportar/importar
# una copia de seguridad siempre opera sobre el perfil que esté activo en
# ese momento, igual que vería esos mismos archivos el resto de la app.
_ARCHIVOS_GLOBALES = {
    "settings.json": "settings",
}
_ARCHIVOS_PERFIL = {
    "favorites.json": "favorites",
    "history.json": "history",
    "tv_channels_custom.json": "custom_tv_channels",
    "radio_stations_custom.json": "custom_radio_stations",
    "torrent_history.json": "torrent_history",
}


def export_backup(destino: str) -> None:
    """
    Vuelca todos los archivos de datos del usuario que existan en un único
    JSON en `destino`. Los que no existan (p. ej. nunca se añadió ningún
    canal personalizado) simplemente no aparecen en el backup — no es un
    error, es lo esperable en una instalación nueva.
    """
    contenido = {
        "app": "TDT & Radio VIP",
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "app_version_at_export": APP_VERSION,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    for nombre_archivo, clave, carpeta in (
        *((n, c, get_app_data_dir()) for n, c in _ARCHIVOS_GLOBALES.items()),
        *((n, c, get_profile_data_dir()) for n, c in _ARCHIVOS_PERFIL.items()),
    ):
        ruta = carpeta / nombre_archivo
        if not ruta.exists():
            continue
        try:
            contenido[clave] = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # Un archivo de origen corrupto no debe tumbar todo el backup;
            # simplemente se omite esa pieza concreta.
            continue

    write_json_atomic(Path(destino), contenido, indent=2)


def import_backup(origen: str) -> list[str]:
    """
    Restaura un backup generado por export_backup(), sobrescribiendo los
    archivos actuales del perfil activo (y los ajustes globales). Devuelve
    la lista de qué se ha restaurado (para poder mostrarlo en la
    interfaz), y lanza ValueError si el archivo no tiene la pinta de ser
    un backup válido de esta app.
    """
    datos = json.loads(Path(origen).read_text(encoding="utf-8"))
    if (
        not isinstance(datos, dict)
        or datos.get("app") != "TDT & Radio VIP"
        or type(datos.get("backup_format_version")) is not int
        or datos.get("backup_format_version") != BACKUP_FORMAT_VERSION
    ):
        raise ValueError("Ese archivo no es una copia de seguridad de TDT & Radio VIP.")

    files = (
        *((n, c, get_app_data_dir()) for n, c in _ARCHIVOS_GLOBALES.items()),
        *((n, c, get_profile_data_dir()) for n, c in _ARCHIVOS_PERFIL.items()),
    )
    for _file_name, key, _directory in files:
        if key not in datos:
            continue
        expected_type = dict if key == "settings" else list
        if not isinstance(datos[key], expected_type):
            raise ValueError(f"La sección {key!r} no tiene un tipo válido.")

    values: dict[Path, object] = {}
    restored: list[str] = []
    for file_name, key, directory in files:
        if key not in datos:
            continue
        values[directory / file_name] = datos[key]
        restored.append(key)

    replace_json_files_atomically(values, indent=2)
    return restored


def sugerir_nombre_backup() -> str:
    """Nombre de archivo sugerido para el diálogo de guardar."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    return f"TDTRadioVIP_backup_{fecha}.json"

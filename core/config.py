"""
Configuración y rutas de la aplicación.
Coder By X@R - TDT & Radio VIP
"""
import logging
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from core.json_store import read_json, write_json_atomic


logger = logging.getLogger(__name__)

APP_NAME = "TDTRadioVIP"
APP_ORG = "CoderByXR"
APP_VERSION = "7.5.7"

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    # Guía XMLTV gratuita de España (proyecto EPG_dobleM, activo desde hace
    # años y actualizado varias veces al día -- ver
    # https://github.com/davidmuma/EPG_dobleM). Es solo un valor de arranque
    # razonable para instalaciones nuevas -- el usuario puede cambiarla o
    # vaciarla libremente desde Configuración > Preferencias, igual que con
    # cualquier otra URL.
    #
    # Antes de la 6.4.1 el valor por defecto era el EPG de globetvapp, que
    # dejó de recibir programación nueva -- ver _migrate_legacy_epg_url()
    # más abajo para la migración de instalaciones ya existentes.
    "epg_url": "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/master/guiatv.xml",
    "volume": 80,
    "recordings_dir": None,
    "downloads_dir": None,
    # "tv_playlist_url" es una anulación manual para usuarios avanzados: si
    # está vacía (el caso normal), la URL se construye a partir de
    # "tv_country_code" — ver core/channels.playlist_url_for(). Se deja vacía
    # por defecto para que el país mande.
    "tv_playlist_url": "",
    "tv_country_code": "ES",
    "radio_country_code": "ES",
    "accent_color": "#c9a227",
    # Se pone a True la primera vez que se muestra el tour de bienvenida
    # (ver ui/onboarding.py), para no volver a enseñarlo en cada arranque.
    "onboarding_shown": False,
    # Modo "solo audio" para canales de TV (desactiva la pista de vídeo
    # para ahorrar CPU/batería) -- ver
    # PlaybackController.toggle_audio_only_tv(). Persistente entre
    # sesiones, no un estado de "esta reproducción concreta".
    "audio_only_tv": False,
    # URL opcional (vacía = comprobación de actualizaciones desactivada,
    # igual que epg_url) de un JSON {"version": "X.Y.Z", "url": "..."} con
    # la última versión publicada. Ver core/updater.py.
    "update_check_url": "",
    # Perfil activo -- "Default" es la carpeta raíz de siempre (ver
    # get_profile_data_dir() más abajo), así que instalaciones existentes
    # no cambian de sitio sus datos al actualizar a esta versión.
    "active_profile": "Default",
    # Ecualizador de audio (TV y radio, ver player/vlc_player.py y
    # ui/equalizer_dialog.py). "equalizer_bands" se deja vacío por defecto
    # a propósito: el número de bandas lo decide libVLC en tiempo de
    # ejecución (equalizer_band_count()), no un valor fijo de aquí -- se
    # rellena con ceros (plano) la primera vez que se abre el diálogo.
    "equalizer_enabled": False,
    "equalizer_preamp": 0.0,
    "equalizer_bands": [],
}

# URL fija que usaban las versiones anteriores a la selección de país (solo
# España, sin desplegable). Sirve para detectar instalaciones antiguas en
# load_settings() y migrarlas al nuevo esquema por código de país en vez de
# dejarlas ancladas para siempre a esa URL como si fuera una anulación manual.
_LEGACY_TV_PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/es.m3u"


@lru_cache(maxsize=1)
def get_app_data_dir() -> Path:
    """
    Carpeta de datos de la app en %APPDATA% (Windows) o home (otros SO).
    Cacheada: se consulta en cada descarga, grabación y carga de logo, y no
    tiene sentido repetir los mkdir cada vez.
    """
    base = os.getenv("APPDATA") or str(Path.home())
    path = Path(base) / APP_ORG / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    (path / "recordings").mkdir(exist_ok=True)
    (path / "cache").mkdir(exist_ok=True)
    return path


# --------------------------------------------------------------------------
# Perfiles de usuario
# --------------------------------------------------------------------------
#
# Pensados para que varias personas que comparten el mismo PC (o un mismo
# usuario con "familia" y "solo" separados) no mezclen favoritos, historial,
# canales/emisoras propias ni grabaciones programadas. Diseño a propósito
# retrocompatible: el perfil "Default" ES la carpeta raíz de siempre
# (get_app_data_dir()), así que quien actualiza sin crear ningún perfil
# nuevo no nota ningún cambio -- sus datos ya estaban ahí. Solo los
# perfiles adicionales que cree el usuario viven en su propia subcarpeta.
#
# No todo se separa por perfil: settings.json, logs, cache/
# y tools/ siguen siendo compartidos (son ajustes de la instalación, no
# datos de "quién los usa"), igual que la guía EPG. Solo lo que de verdad identifica a una persona -- favoritos,
# historial, canales/emisoras añadidos a mano y grabaciones programadas --
# se separa. Ver core/favorites.py, core/history.py, core/channels.py,
# core/radio.py y core/recording_schedule.py.

PROFILES_DIR_NAME = "profiles"
DEFAULT_PROFILE = "Default"


@lru_cache(maxsize=None)
def _profile_dir_for(profile: str) -> Path:
    if profile == DEFAULT_PROFILE:
        return get_app_data_dir()
    path = get_app_data_dir() / PROFILES_DIR_NAME / profile
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_profile_data_dir(profile: Optional[str] = None) -> Path:
    """Carpeta de datos del perfil indicado (o del perfil activo, si no se
    especifica ninguno) -- ver el bloque de comentario de arriba."""
    return _profile_dir_for(profile or get_current_profile())


def list_profiles() -> list:
    """["Default", ...] -- Default siempre presente y siempre primero."""
    base = get_app_data_dir() / PROFILES_DIR_NAME
    perfiles = [DEFAULT_PROFILE]
    if base.exists():
        perfiles += sorted(p.name for p in base.iterdir() if p.is_dir())
    return perfiles


def get_current_profile() -> str:
    return load_settings().get("active_profile", DEFAULT_PROFILE)


def set_current_profile(profile: str) -> bool:
    settings = load_settings()
    settings["active_profile"] = profile
    return save_settings(settings)


_PROFILE_NAME_CHARS_PROHIBIDOS = set('\\/:*?"<>|')


def create_profile(name: str) -> str:
    """Crea (si no existía) el perfil `name` y devuelve su nombre ya
    saneado (sin espacios sobrantes).

    El nombre se usa tal cual como componente de carpeta bajo
    profiles/ (ver _profile_dir_for) -- sin validar, un nombre como
    "..\\Otro" o "../../Escritorio" escaparía de esa carpeta y
    crearía/escribiría rutas fuera del árbol de datos de la app.
    """
    name = name.strip()
    if not name or name in (".", "..") or _PROFILE_NAME_CHARS_PROHIBIDOS & set(name):
        raise ValueError(f"Nombre de perfil no válido: {name!r}")
    _profile_dir_for(name)  # crea la carpeta y la deja en caché
    return name


# --------------------------------------------------------------------------
# Localización de ffmpeg (único punto de verdad para toda la app)
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_ffmpeg_dir() -> Optional[str]:
    """
    Carpeta del ffmpeg empaquetado con la app, o None si no viaja incluido.

    Al ejecutar como EXE (PyInstaller) el contenido se extrae a sys._MEIPASS;
    en desarrollo se busca en resources/ffmpeg del propio proyecto.
    """
    base_dir = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    candidato = os.path.join(base_dir, "resources", "ffmpeg")
    nombre = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if os.path.isfile(os.path.join(candidato, nombre)):
        return candidato
    return None


@lru_cache(maxsize=1)
def get_ffmpeg_exe() -> Optional[str]:
    """
    Ruta al ejecutable de ffmpeg utilizable, o None si no hay ninguno.

    Prioriza el ffmpeg empaquetado: en un PC sin ffmpeg instalado (el caso
    normal de quien recibe el EXE) el PATH no lo tiene, y buscarlo solo ahí
    dejaba la grabación inservible pese a ir incluido en el ejecutable.
    """
    carpeta = get_ffmpeg_dir()
    if carpeta:
        nombre = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        return os.path.join(carpeta, nombre)
    return shutil.which("ffmpeg")


@lru_cache(maxsize=1)
def get_icon_path() -> Optional[str]:
    """
    Ruta al icono de la app (resources/icon.ico), empaquetado con el EXE o
    presente en el proyecto en desarrollo. None si no se encuentra.

    Punto único de verdad para todo lo que necesite el .ico: antes main.py
    y main_free.py calculaban esta misma ruta cada uno por su cuenta con
    sys._MEIPASS, y ui/main_window.py no tenía forma de encontrarlo por sí
    misma para fijar el icono nativo de la ventana (ver _set_native_icon en
    ui/taskbar_controls.py) — con un icon=None ahí, ese fix no hacía nada.
    """
    base_dir = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    candidato = os.path.join(base_dir, "resources", "icon.ico")
    return candidato if os.path.isfile(candidato) else None


def load_settings() -> dict:
    path = get_app_data_dir() / SETTINGS_FILE
    settings = DEFAULT_SETTINGS.copy()
    data = read_json(path, {})
    if isinstance(data, dict):
        settings.update(data)
    if not settings.get("recordings_dir"):
        settings["recordings_dir"] = str(get_app_data_dir() / "recordings")
    _migrate_legacy_country_settings(settings)
    _migrate_legacy_epg_url(settings)
    return settings


_LEGACY_EPG_URL = "https://raw.githubusercontent.com/globetvapp/epg/main/Spain/spain2.xml"


def _migrate_legacy_epg_url(settings: dict) -> None:
    """
    El EPG de globetvapp (valor por defecto hasta la 6.4.1) dejó de recibir
    programación nueva. Si el usuario nunca tocó esa preferencia (sigue
    siendo exactamente ese valor por defecto antiguo), se cambia sola al
    nuevo por defecto -- si en cambio puso su propia URL a mano, esa
    elección se respeta y no se toca.
    """
    if settings.get("epg_url") == _LEGACY_EPG_URL:
        settings["epg_url"] = DEFAULT_SETTINGS["epg_url"]


def _migrate_legacy_country_settings(settings: dict) -> None:
    """
    Instalaciones de antes del selector de país guardaban la URL de TV fija
    a España y un "radio_country": "Spain" en vez de un código. Sin esto, un
    usuario que actualiza vería su "tv_playlist_url" antigua tratada como
    anulación manual y el nuevo selector de país no tendría ningún efecto.
    """
    if settings.get("tv_playlist_url") == _LEGACY_TV_PLAYLIST_URL:
        settings["tv_playlist_url"] = ""
        settings.setdefault("tv_country_code", "ES")

    old_radio_country = settings.pop("radio_country", None)
    if old_radio_country and not settings.get("radio_country_code"):
        # El único valor que existió en versiones anteriores era "Spain"
        # (no había desplegable de país); de ahí el único mapeo conocido.
        settings["radio_country_code"] = {"Spain": "ES"}.get(old_radio_country, "ES")


def save_settings(settings: dict) -> bool:
    path = get_app_data_dir() / SETTINGS_FILE
    try:
        write_json_atomic(path, settings, indent=2)
    except OSError:
        logger.warning("No se pudieron guardar los ajustes en %s", path, exc_info=True)
        return False
    return True

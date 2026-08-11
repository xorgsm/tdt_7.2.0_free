"""
Logging centralizado a disco.

Hasta ahora, casi todos los fallos de zonas delicadas (Chromecast, grabación,
descargas, reproducción) se tragaban en silencio con "except Exception:
pass". Si un cliente dice "se cuelga al enviar a la TV" o "no graba", no
había ningún rastro para diagnosticarlo sin reproducirlo tú mismo.

Uso:
    from core.logger import get_logger
    log = get_logger(__name__)
    ...
    try:
        algo_arriesgado()
    except Exception:
        log.exception("Fallo al hacer X con el canal %s", nombre_canal)

Coder By X@R
"""
import logging
from logging.handlers import RotatingFileHandler

from core.config import get_app_data_dir

_LOG_DIR = get_app_data_dir() / "logs"
_LOG_FILE = _LOG_DIR / "app.log"

_configurado = False


def _configurar_raiz():
    """
    Configura el logger raíz una sola vez, la primera vez que algo pide un
    logger. Rotación a 2 MB con 3 copias de respaldo: suficiente para
    varias sesiones de uso sin que el archivo crezca sin límite.
    """
    global _configurado
    if _configurado:
        return
    _configurado = True

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Si ni siquiera se puede crear la carpeta de logs (permisos,
        # disco lleno...), seguimos sin logging a archivo en vez de
        # bloquear el arranque de la app por esto.
        return

    handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(handler)


def get_logger(nombre: str) -> logging.Logger:
    """Logger con el nombre del módulo que lo pide (típicamente __name__)."""
    _configurar_raiz()
    return logging.getLogger(nombre)


def log_file_path():
    """Ruta del archivo de log actual, para mostrarla en la UI (p. ej. un
    botón "Abrir carpeta de logs" en Ayuda) sin duplicar la ruta a mano."""
    return _LOG_FILE

"""
Arranque común a los distintos puntos de entrada (main.py, main_free.py).

Antes cada uno tenía su propia copia letra por letra del fix de
AppUserModelID y de la preparación de VLC empaquetado -- un cambio hecho
en un archivo se olvidaba fácilmente en el otro (p. ej. el fix del icono
de ventana en main.py). Centralizado aquí, un solo sitio que mantener.

Debe importarse y usarse ANTES de crear QApplication y antes de que nada
importe player.vlc_player -- ver el orden exacto en main.py / main_free.py.

Coder By X@R
"""
import os
import sys


def set_app_user_model_id(app_user_model_id: str) -> None:
    """
    Fija el AppUserModelID de Windows para este proceso.

    Sin esto, Windows a veces no asocia bien esta ventana con "su" icono en
    la barra de tareas / vista previa al pasar el ratón, aunque el icono en
    sí esté bien puesto -- cae al genérico de Qt/Python en su lugar. Cada
    build (con licencia, Free) usa un id distinto para que Windows no las
    mezcle en la barra de tareas si el usuario tiene las dos instaladas a
    la vez. No hace nada fuera de Windows.
    """
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_user_model_id)
    except Exception:
        pass  # en Windows muy antiguos esta llamada puede no existir


def prepare_bundled_vlc() -> None:
    """
    Prepara el entorno para que python-vlc encuentre libvlc y sus plugins
    cuando viajan empaquetados con la app (ver TDTRadioVIP.spec /
    TDTRadioVIP_Free.spec), tanto en desarrollo como ya compilada a EXE.

    Debe llamarse antes de que cualquier módulo importe python-vlc
    (típicamente player.vlc_player) -- las variables de entorno y el
    directorio DLL no tienen efecto si se fijan después de que la
    librería ya se cargó.
    """
    base_dir = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    plugins_dir = os.path.join(base_dir, "plugins")
    if os.path.isdir(plugins_dir):
        os.environ["VLC_PLUGIN_PATH"] = plugins_dir
    if hasattr(os, "add_dll_directory") and os.path.isdir(base_dir):
        try:
            os.add_dll_directory(base_dir)
        except OSError:
            pass


def bootstrap(app_user_model_id: str) -> None:
    """Atajo para las dos llamadas anteriores, en el orden correcto."""
    set_app_user_model_id(app_user_model_id)
    prepare_bundled_vlc()

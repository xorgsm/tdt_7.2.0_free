"""
TDT & Radio VIP - Versión FREE COMPLETA
Coder By X@R
Arranca directamente sin pedir código de activación.
Todas las funciones desbloqueadas.
"""
import sys

# Ver core/bootstrap.py — mismo fix que main.py, id distinto para que
# Windows no mezcle esta build Free con la que tiene licencia en la barra
# de tareas si están las dos instaladas a la vez.
from core.bootstrap import bootstrap

bootstrap("CoderByXR.TDTRadioVIP.Free")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.style import build_style, DEFAULT_ACCENT
from core.config import APP_VERSION, get_icon_path, load_settings
from player.vlc_player import vlc_disponible_al_arrancar


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TDT & Radio VIP")
    app.setApplicationVersion(APP_VERSION)
    ajustes = load_settings()
    app.setStyleSheet(build_style(ajustes.get("accent_color", DEFAULT_ACCENT)))

    icon_path = get_icon_path()
    app_icon = QIcon(icon_path) if icon_path else QIcon()
    app.setWindowIcon(app_icon)

    aviso_vlc = vlc_disponible_al_arrancar()
    if aviso_vlc:
        QMessageBox.warning(None, "VLC no encontrado", aviso_vlc)

    # Sin splash, sin activación: todas las funciones activas desde el inicio.
    window = MainWindow(activated=True, es_version_free=True)
    # Ver el comentario en main.py: con ventana sin bordes nativos hay que
    # fijar el icono también en la propia ventana, no solo en QApplication,
    # o la barra de tareas de Windows puede mostrar el genérico.
    window.setWindowIcon(app_icon)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

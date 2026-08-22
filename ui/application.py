"""Inicialización de la edición Free de la aplicación."""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import APP_VERSION, get_icon_path, load_settings
from player.vlc_player import vlc_disponible_al_arrancar
from ui.main_window import MainWindow
from ui.style import DEFAULT_ACCENT, build_style


def _create_application() -> tuple[QApplication, QIcon]:
    app = QApplication(sys.argv)
    app.setApplicationName("TDT & Radio VIP")
    app.setApplicationVersion(APP_VERSION)
    settings = load_settings()
    app.setStyleSheet(build_style(settings.get("accent_color", DEFAULT_ACCENT)))

    icon_path = get_icon_path()
    app_icon = QIcon(icon_path) if icon_path else QIcon()
    app.setWindowIcon(app_icon)

    vlc_warning = vlc_disponible_al_arrancar()
    if vlc_warning:
        QMessageBox.warning(None, "VLC no encontrado", vlc_warning)
    return app, app_icon


def run_free() -> int:
    """Ejecuta la edición Free."""
    app, app_icon = _create_application()
    window = MainWindow(activated=True, es_version_free=True)
    window.setWindowIcon(app_icon)
    window.show()
    return app.exec()

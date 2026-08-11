"""
Configuración compartida de pytest.

Mismo truco que tools/keygen.py para poder hacer "import core..." sin
depender de cómo se invoque pytest (desde la raíz del proyecto, desde
tests/, o vía un IDE) ni de que el proyecto esté instalado como paquete.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """QApplication real y sin pantalla para contratos visuales."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def carpeta_datos_aislada(tmp_path, monkeypatch):
    """
    Redirige get_app_data_dir() a una carpeta temporal distinta en cada
    test, para que las pruebas de config/license/backup lean y escriban
    ahí en vez de tocar el %APPDATA% real de quien ejecute pytest (y para
    que un test no vea restos que dejó otro).

    get_app_data_dir() está decorada con @lru_cache -- sin limpiarla antes
    y después de cada test, la carpeta calculada en el primer test que la
    llama se quedaría fija para todos los siguientes, ignorando el
    monkeypatch de APPDATA.
    """
    from core import config

    monkeypatch.setenv("APPDATA", str(tmp_path))
    config.get_app_data_dir.cache_clear()
    config._profile_dir_for.cache_clear()
    yield
    config.get_app_data_dir.cache_clear()
    config._profile_dir_for.cache_clear()

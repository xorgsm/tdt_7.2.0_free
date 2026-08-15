"""
Pruebas de core/logger.py: get_logger() debe devolver loggers con el
nombre pedido, y no debe bloquear el arranque de la app si no se puede
crear la carpeta de logs (permisos, disco lleno...).
"""
import logging

from core import logger as logger_module


def test_get_logger_devuelve_logger_con_el_nombre_pedido():
    log = logger_module.get_logger("modulo.de.prueba")
    assert isinstance(log, logging.Logger)
    assert log.name == "modulo.de.prueba"


def test_log_file_path_devuelve_la_ruta_configurada():
    ruta = logger_module.log_file_path()
    assert ruta.name == "app.log"


def test_configurar_raiz_no_explota_si_no_puede_crear_la_carpeta(monkeypatch):
    class _CarpetaQueFalla:
        def mkdir(self, parents=True, exist_ok=True):
            raise OSError("disco lleno")

    logger_module._configurado = False
    monkeypatch.setattr(logger_module, "_LOG_DIR", _CarpetaQueFalla())

    # No debe lanzar excepción -- se queda sin logging a archivo en vez de
    # impedir que la app arranque.
    logger_module._configurar_raiz()

    assert logger_module._configurado is True
    logger_module._configurado = False  # no perturbar otros tests de la sesión

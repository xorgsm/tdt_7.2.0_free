"""
Diálogo 'Enviar a la TV': busca Chromecasts / TVs con Google Cast Y
televisores con DLNA/UPnP en la red local (en paralelo) y deja elegir uno.
Coder By X@R
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from core.caster import pychromecast_available, CastDiscoveryWorker
from core.dlna_caster import DLNADiscoveryWorker
from ui import palette
from ui.visual import set_surface

# Backends posibles para un dispositivo listado, guardados en Qt.UserRole
# junto al nombre, para saber a qué clase de sesión enrutar al aceptar.
BACKEND_CHROMECAST = "chromecast"
BACKEND_DLNA = "dlna"


class CastDeviceDialog(QDialog):
    """Busca dispositivos Google Cast y DLNA, y deja elegir uno para enviar contenido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Enviar a la TV")
        self.setMinimumWidth(360)
        self.selected_name = None
        self.selected_backend = None
        self._cc_worker = None
        self._dlna_worker = None
        self._pendientes = 0
        self._total_encontrados = 0

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Buscando dispositivos en tu red…")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {palette.TEXT_MUTED};")
        layout.addWidget(self.status_label)

        self.device_list = QListWidget()
        self.device_list.itemDoubleClicked.connect(lambda _: self._accept_if_selected())
        layout.addWidget(self.device_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enviar")
        buttons.accepted.connect(self._accept_if_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if pychromecast_available():
            self._pendientes += 1
            self._cc_worker = CastDiscoveryWorker(self)
            self._cc_worker.found.connect(
                lambda names: self._on_found(BACKEND_CHROMECAST, names)
            )
            self._cc_worker.start()

        self._pendientes += 1
        self._dlna_worker = DLNADiscoveryWorker(self)
        self._dlna_worker.found.connect(lambda names: self._on_found(BACKEND_DLNA, names))
        self._dlna_worker.start()

    def _on_found(self, backend: str, names: list):
        self._pendientes -= 1
        for name in names:
            item = QListWidgetItem(self._label_for(backend, name))
            item.setData(Qt.UserRole, (backend, name))
            self.device_list.addItem(item)
            self._total_encontrados += 1

        if self._pendientes > 0:
            return  # aún falta el otro descubrimiento por terminar

        if self._total_encontrados == 0:
            self.status_label.setText(
                "No se encontró ningún Chromecast ni TV con DLNA en tu red.\n"
                "Comprueba que el PC y la TV están en la misma red WiFi."
            )
            return

        self.status_label.setText(f"{self._total_encontrados} dispositivo(s) encontrado(s):")
        self.device_list.setCurrentRow(0)

    @staticmethod
    def _label_for(backend: str, name: str) -> str:
        etiqueta = "Google Cast" if backend == BACKEND_CHROMECAST else "DLNA"
        return f"{name}  ·  {etiqueta}"

    def _accept_if_selected(self):
        item = self.device_list.currentItem()
        if item is None:
            return
        self.selected_backend, self.selected_name = item.data(Qt.UserRole)
        self.accept()

    def done(self, result):
        """
        Al cerrarse el diálogo, desconecta las señales de los hilos de
        búsqueda. Sin esto, si el usuario cierra antes de que termine el
        descubrimiento (que tarda varios segundos), los hilos intentarían
        emitir hacia un objeto ya destruido y la aplicación se cerraría de
        golpe.
        """
        if self._cc_worker is not None:
            try:
                self._cc_worker.found.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self._dlna_worker is not None:
            try:
                self._dlna_worker.found.disconnect()
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    def get_worker(self, backend: str = BACKEND_CHROMECAST):
        return self._cc_worker if backend == BACKEND_CHROMECAST else self._dlna_worker

    def release_worker(self):
        """
        Libera el explorador zeroconf de Chromecast y espera a que ambos
        hilos de búsqueda terminen. Debe llamarse SIEMPRE al acabar de usar
        el dispositivo elegido (o al cancelar).
        """
        if self._cc_worker is not None:
            self._cc_worker.stop_discovery()
            if self._cc_worker.isRunning():
                self._cc_worker.wait(3000)
            self._cc_worker = None
        if self._dlna_worker is not None:
            if self._dlna_worker.isRunning():
                self._dlna_worker.wait(3000)
            self._dlna_worker = None

"""
Diálogo "Estadísticas de uso": ranking de canales/emisoras más
reproducidos y un resumen rápido de TV vs radio, a partir del propio
historial (core/history.py) -- no hace falta ningún tracking nuevo aparte
del play_count que ya lleva add_entry().

Coder By X@R
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QVBoxLayout, QWidget,
)

from core import history as history_module
from ui import palette
from ui.visual import set_surface


class StatsDialog(QDialog):
    """Se abre desde Ayuda > Estadísticas de uso. Solo lectura."""

    def __init__(self, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Estadísticas de uso")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        registros = history_module.load_history()
        total_tv = sum(1 for e in registros if e.get("type") == "tv")
        total_radio = sum(1 for e in registros if e.get("type") == "radio")

        resumen = QLabel(
            f"{len(registros)} canales/emisoras distintos en el historial "
            f"({total_tv} de TV, {total_radio} de radio)."
        )
        resumen.setWordWrap(True)
        resumen.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8.5pt;")
        root.addWidget(resumen)

        titulo_top = QLabel("Lo más reproducido")
        titulo_top.setStyleSheet("font-weight: 600; font-size: 10pt; margin-top: 4px;")
        root.addWidget(titulo_top)

        top = history_module.top_played(registros, limit=10)
        if not top:
            vacio = QLabel("Todavía no hay historial de reproducción.")
            vacio.setStyleSheet(f"color: {palette.TEXT_MUTED};")
            root.addWidget(vacio)
        else:
            lista = QListWidget()
            lista.setObjectName("channelList")
            maximo = max(e.get("play_count", 1) for e in top)
            for entrada in top:
                item, widget = self._fila(entrada, maximo)
                lista.addItem(item)
                lista.setItemWidget(item, widget)
            root.addWidget(lista, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    @staticmethod
    def _fila(entrada: dict, maximo: int):
        """Devuelve (item, widget): widget se asigna con setItemWidget()
        en el sitio donde se conoce la QListWidget destino."""
        veces = entrada.get("play_count", 1)
        glifo = "📺" if entrada.get("type") == "tv" else "📻"
        texto = f"{glifo}  {entrada.get('name', '')}"
        sufijo = "vez" if veces == 1 else "veces"

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        label = QLabel(texto)
        label.setStyleSheet(f"color: {palette.TEXT_PRIMARY};")
        layout.addWidget(label, stretch=1)

        barra = QProgressBar()
        barra.setFixedWidth(90)
        barra.setFixedHeight(10)
        barra.setTextVisible(False)
        barra.setRange(0, maximo)
        barra.setValue(veces)
        barra.setStyleSheet(
            f"QProgressBar {{ background: {palette.BG_PANEL_ALT}; border: none; "
            f"border-radius: 5px; }} QProgressBar::chunk {{ background: {palette.ACCENT}; "
            f"border-radius: 5px; }}"
        )
        layout.addWidget(barra)

        contador = QLabel(f"{veces} {sufijo}")
        contador.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8pt;")
        contador.setFixedWidth(50)
        contador.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(contador)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        return item, widget

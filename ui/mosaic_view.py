"""
Multivista: hasta MAX_TILES canales de TV a la vez en un mosaico, cada
uno con su propia instancia de VLCPlayer (ver player/vlc_player.py).

Decodificar varios streams de vídeo a la vez es bastante más caro que
reproducir uno solo, que es lo único que hace el resto de la aplicación.
Por eso esta vista se diseña a propósito de forma conservadora:

  - Solo existe mientras el usuario tiene el diálogo abierto -- no hay
    nada de esto corriendo de fondo el resto del tiempo, así que no
    afecta en nada al rendimiento normal de la app.
  - Se limita a MAX_TILES canales (4) como máximo.
  - Cada VLCPlayer se libera (release()) religiosamente al cerrar el
    diálogo o al volver a elegir canales, para no dejar decodificadores
    ni hilos de libVLC vivos de más.
  - Solo el mosaico "enfocado" lleva audio (como las vistas multi-cámara
    de cualquier plataforma de streaming): los demás se reproducen
    mudos, así que el coste real que importa es solo el de vídeo.

Coder By X@R
"""
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.channels import Channel
from player.vlc_player import VLCPlayer
from ui import palette
from ui.visual import set_surface

MAX_TILES = 4


class _SelectorCanales(QWidget):
    """Paso 1 del diálogo: elegir hasta MAX_TILES canales de TV."""

    def __init__(self, canales: List[Channel], on_iniciar, parent=None):
        super().__init__(parent)
        self._on_iniciar = on_iniciar
        self._checks = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        titulo = QLabel(f"Elige hasta {MAX_TILES} canales para ver a la vez")
        titulo.setStyleSheet("font-weight: 600; font-size: 11pt;")
        root.addWidget(titulo)

        aviso = QLabel(
            "Reproducir varios canales a la vez consume más CPU que uno solo. "
            "Con menos canales a la vez el mosaico va más fluido."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8.5pt;")
        root.addWidget(aviso)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contenedor = QWidget()
        lista_layout = QVBoxLayout(contenedor)
        lista_layout.setSpacing(2)
        for ch in canales:
            cb = QCheckBox(ch.name)
            cb.toggled.connect(self._on_toggle)
            lista_layout.addWidget(cb)
            self._checks.append((cb, ch))
        lista_layout.addStretch(1)
        scroll.setWidget(contenedor)
        root.addWidget(scroll, stretch=1)

        self.iniciar_btn = QPushButton("Iniciar multivista")
        self.iniciar_btn.setEnabled(False)
        self.iniciar_btn.clicked.connect(lambda: self._on_iniciar(self.seleccionados()))
        root.addWidget(self.iniciar_btn)

    def _on_toggle(self, _checked):
        if len(self.seleccionados()) > MAX_TILES:
            # Se deshace el clic que se pasó del límite, en vez de bloquear
            # el checkbox a medias -- más predecible para quien lo usa.
            sender = self.sender()
            sender.blockSignals(True)
            sender.setChecked(False)
            sender.blockSignals(False)
        self.iniciar_btn.setEnabled(1 <= len(self.seleccionados()) <= MAX_TILES)

    def seleccionados(self) -> List[Channel]:
        return [ch for cb, ch in self._checks if cb.isChecked()]


class _MosaicTile(QWidget):
    """Un canal dentro del mosaico: vídeo + nombre, con borde resaltado
    cuando tiene el foco de audio. Al pinchar, pide el foco."""

    def __init__(self, channel: Channel, index: int, on_focus):
        super().__init__()
        self.channel = channel
        self.index = index
        self._on_focus = on_focus
        self._focado = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.player = VLCPlayer(self)
        self.player.setMinimumSize(160, 120)
        layout.addWidget(self.player, stretch=1)

        self.nombre_label = QLabel(channel.name)
        self.nombre_label.setAlignment(Qt.AlignCenter)
        self.nombre_label.setStyleSheet(
            f"background-color: {palette.BG_PANEL}; color: {palette.TEXT_PRIMARY}; "
            f"font-size: 8.5pt; padding: 3px;"
        )
        layout.addWidget(self.nombre_label)

        self._aplicar_borde()

    def set_focus(self, focado: bool):
        self._focado = focado
        self.player.set_muted(not focado)
        self._aplicar_borde()

    def _aplicar_borde(self):
        color = palette.ACCENT if self._focado else palette.BORDER
        grosor = 3 if self._focado else 1
        self.setStyleSheet(f"border: {grosor}px solid {color};")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_focus(self.index)
        super().mousePressEvent(event)


class MosaicView(QDialog):
    """Diálogo de multivista: selector de canales, luego mosaico 2x2."""

    def __init__(self, parent, canales: List[Channel]):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Multivista")
        self.resize(760, 560)
        self._canales_disponibles = canales
        self._tiles: List[_MosaicTile] = []

        self._stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._pagina_selector = _SelectorCanales(canales, self._iniciar_mosaico)
        self._stack.addWidget(self._pagina_selector)

        self._pagina_mosaico = QWidget()
        self._grid = QGridLayout(self._pagina_mosaico)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(6)
        botones_row = QHBoxLayout()
        cambiar_btn = QPushButton("← Elegir otros canales")
        cambiar_btn.clicked.connect(self._volver_al_selector)
        botones_row.addWidget(cambiar_btn)
        botones_row.addStretch(1)

        contenedor_mosaico = QWidget()
        contenedor_layout = QVBoxLayout(contenedor_mosaico)
        contenedor_layout.setContentsMargins(10, 10, 10, 10)
        contenedor_layout.addLayout(botones_row)
        contenedor_layout.addWidget(self._pagina_mosaico, stretch=1)
        self._stack.addWidget(contenedor_mosaico)

    # ---------- selección y arranque ----------

    def _iniciar_mosaico(self, canales_elegidos: List[Channel]):
        if not canales_elegidos:
            return
        self._liberar_tiles()

        filas_cols = {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2)}
        _filas, columnas = filas_cols.get(len(canales_elegidos), (2, 2))

        for i, canal in enumerate(canales_elegidos[:MAX_TILES]):
            tile = _MosaicTile(canal, i, self._enfocar)
            self._tiles.append(tile)
            fila, col = divmod(i, columnas)
            self._grid.addWidget(tile, fila, col)
            tile.player.play(canal.url)

        self._enfocar(0)
        self._stack.setCurrentIndex(1)

    def _enfocar(self, index: int):
        for tile in self._tiles:
            tile.set_focus(tile.index == index)

    def _volver_al_selector(self):
        self._liberar_tiles()
        self._stack.setCurrentIndex(0)

    # ---------- limpieza ----------

    def _liberar_tiles(self):
        for tile in self._tiles:
            tile.player.release()
            self._grid.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []

    def closeEvent(self, event):
        self._liberar_tiles()
        super().closeEvent(event)

    def reject(self):
        self._liberar_tiles()
        super().reject()

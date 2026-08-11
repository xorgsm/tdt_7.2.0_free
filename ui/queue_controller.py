"""
Cola de reproducción "Reproduciendo a continuación", estilo Spotify.

Guarda una lista en memoria (self.win._queue) de canales/emisoras que el
usuario ha puesto en cola desde el menú contextual. No se persiste a disco
a propósito: es una cola de la sesión actual — al cerrar la app se vacía,
igual que en Spotify. Guardar canales de forma permanente ya lo cubren los
favoritos (con carpetas incluso), así que no hace falta una "cola guardada"
aparte.

Sigue el mismo patrón de extracción que PlaybackController / WindowChrome /
ChannelListsController: recibe la ventana en el constructor (self.win) y
opera sobre su estado, en vez de duplicar estado propio.

Coder By X@R
"""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from ui import palette

ROLE_QUEUE_DATA = Qt.UserRole + 50


class QueueController:
    """Gestiona la cola "Reproduciendo a continuación" de MainWindow."""

    def __init__(self, window):
        self.win = window
        self.win._queue = []
        self._dialog = None
        self._list_widget = None
        self._panel_fade_anim = None

    # ---------- Estado ----------

    def has_items(self) -> bool:
        return bool(self.win._queue)

    def add(self, data: dict):
        """Añade un canal/emisora al final de la cola."""
        if not data or not data.get("url"):
            return
        self.win._queue.append(dict(data))
        self.win.statusBar().showMessage(f"«{data.get('name', '')}» añadido a la cola.", 4000)
        self._refresh_button_badge()
        if self._list_widget is not None:
            self._render_list()

    def play_next(self) -> bool:
        """
        Reproduce y saca de la cola el primer elemento pendiente.
        Devuelve True si había algo que reproducir.
        """
        if not self.win._queue:
            return False
        data = self.win._queue.pop(0)
        self.win.playback.play(
            data["type"], data["name"], data["url"],
            data.get("tvg_id", ""), data.get("logo", ""),
        )
        self._refresh_button_badge()
        if self._list_widget is not None:
            self._render_list()
        return True

    def clear(self):
        self.win._queue.clear()
        self._refresh_button_badge()
        if self._list_widget is not None:
            self._render_list()

    def _refresh_button_badge(self):
        btn = getattr(self.win, "queue_btn", None)
        if btn is None:
            return
        n = len(self.win._queue)
        btn.setToolTip(f"Cola de reproducción ({n})" if n else "Cola de reproducción (vacía)")

    # ---------- Panel emergente ----------

    def toggle_panel(self):
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.close()
            return
        self._build_panel()
        # Ancla a more_btn: queue_btn ya no vive en ningún layout visible
        # (ver ui/main_window.py _build_now_playing_bar) y su posición en
        # pantalla no sería fiable para mapToGlobal.
        btn = self.win.more_btn
        pos = btn.mapToGlobal(btn.rect().bottomRight())
        self._dialog.adjustSize()
        self._dialog.move(pos.x() - self._dialog.width(), pos.y() + 6)
        self._dialog.show()
        self._fade_in(self._dialog)

    def _fade_in(self, widget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        # Referencia guardada para que el recolector de basura de Python no
        # se lleve la animación a medio camino -- mismo motivo que
        # MainWindow._fade_anim en la transición entre secciones.
        self._panel_fade_anim = anim

    def _build_panel(self):
        win = self.win
        dlg = QDialog(win, Qt.Popup)
        dlg.setObjectName("queuePanel")
        dlg.setFixedWidth(300)
        dlg.setStyleSheet(
            f"#queuePanel {{ background-color: {palette.BG_PANEL}; "
            f"border: 1px solid {palette.BORDER}; border-radius: 10px; }}"
            f"QLabel {{ color: {palette.TEXT_PRIMARY}; }}"
        )
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Reproduciendo a continuación")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title, stretch=1)
        clear_btn = QPushButton("Vaciar")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {palette.TEXT_MUTED}; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {palette.ACCENT}; }}"
        )
        clear_btn.clicked.connect(self.clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        lst = QListWidget()
        lst.setObjectName("queueList")
        lst.setDragDropMode(QAbstractItemView.InternalMove)
        lst.setMaximumHeight(280)
        lst.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; color: {palette.TEXT_PRIMARY}; }}"
            f"QListWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {palette.BORDER}; }}"
            f"QListWidget::item:selected {{ background-color: {palette.BG_PANEL_ALT}; }}"
        )
        lst.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(lst)

        self._list_widget = lst
        self._dialog = dlg
        self._render_list()

    def _render_list(self):
        lst = self._list_widget
        if lst is None:
            return
        lst.clear()
        if not self.win._queue:
            item = QListWidgetItem("La cola está vacía.")
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor(palette.TEXT_MUTED))
            lst.addItem(item)
            return
        for data in self.win._queue:
            icon = "TV" if data.get("type") == "tv" else "FM"
            item = QListWidgetItem(f"{icon} · {data.get('name', '')}")
            item.setData(ROLE_QUEUE_DATA, data)
            lst.addItem(item)

    def _on_rows_moved(self, *_args):
        # Tras un arrastre para reordenar, reconstruye self.win._queue con
        # el nuevo orden leído directamente de los items de la lista.
        lst = self._list_widget
        nuevo_orden = []
        for row in range(lst.count()):
            data = lst.item(row).data(ROLE_QUEUE_DATA)
            if data:
                nuevo_orden.append(data)
        if nuevo_orden:
            self.win._queue = nuevo_orden

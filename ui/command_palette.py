"""
Búsqueda global instantánea (Ctrl+K), estilo "paleta de comandos" de
Spotify/VSCode: un cuadro flotante que combina canales de TV, emisoras de
radio y accesos directos a otras secciones en una sola lista, para no tener
que cambiar de pestaña y filtrar cada lista por separado cuando ya se sabe
lo que se busca.

No importa nada de ui.main_window a propósito (evitaría un import
circular, ya que main_window importa este módulo): las acciones rápidas
("Ir a Favoritos", "Preferencias…"...) las construye MainWindow y se pasan
ya hechas al constructor como lista de (etiqueta, función).

Coder By X@R
"""
from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QDialog, QGraphicsOpacityEffect, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ui.visual import set_surface

ROLE_RESULT = Qt.UserRole + 60
MAX_RESULTS = 40


class CommandPalette(QDialog):
    """
    Diálogo de búsqueda global. MainWindow crea uno nuevo cada vez que se
    invoca (Ctrl+K o menú Archivo) en vez de reutilizar una instancia — así
    siempre arranca con el campo vacío y el foco puesto, sin estado que
    limpiar a mano.
    """

    def __init__(self, window, actions):
        super().__init__(window, Qt.Popup)
        self.win = window
        self._actions = actions  # lista de (etiqueta, callback)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("commandPalette")
        set_surface(self, "floating")
        self.setFixedWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("commandSearch")
        self.search_box.setPlaceholderText("Buscar canales, emisoras, ajustes… (Esc para cerrar)")
        self.search_box.textChanged.connect(self._refresh)
        self.search_box.installEventFilter(self)
        layout.addWidget(self.search_box)

        self.results = QListWidget()
        self.results.setObjectName("commandResults")
        self.results.setMaximumHeight(360)
        self.results.itemClicked.connect(self._activate_item)
        self.results.itemActivated.connect(self._activate_item)
        layout.addWidget(self.results)

        self._refresh("")

    # ---------- Búsqueda ----------

    def _refresh(self, query: str):
        query = (query or "").strip().lower()
        self.results.clear()

        for label, callback in self._actions:
            if not query or query in label.lower():
                item = QListWidgetItem(f"→ {label}")
                item.setData(ROLE_RESULT, ("accion", callback))
                self.results.addItem(item)

        if query:
            # tv_channels_data / radio_stations_data guardan instancias de
            # los dataclasses Channel / Station (core/channels.py,
            # core/radio.py) — acceso por atributo, no por .get() como los
            # dict que sí usan los QListWidgetItem de las listas normales.
            count = self.results.count()
            for ch in self.win.tv_channels_data:
                if count >= MAX_RESULTS:
                    break
                if query in ch.name.lower():
                    item = QListWidgetItem(f"TV · {ch.name}")
                    item.setData(ROLE_RESULT, ("tv", ch))
                    self.results.addItem(item)
                    count += 1
            for st in self.win.radio_stations_data:
                if count >= MAX_RESULTS:
                    break
                if query in st.name.lower():
                    item = QListWidgetItem(f"FM · {st.name}")
                    item.setData(ROLE_RESULT, ("radio", st))
                    self.results.addItem(item)
                    count += 1

        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def _activate_item(self, item: QListWidgetItem):
        if item is None:
            return
        kind, payload = item.data(ROLE_RESULT)
        if kind == "accion":
            self.close()
            payload()
            return
        if kind == "tv" and payload.url:
            self.close()
            self.win.playback.play(kind, payload.name, payload.url, payload.tvg_id, payload.logo)
        elif kind == "radio" and payload.url:
            self.close()
            self.win.playback.play(kind, payload.name, payload.url, "", payload.favicon)

    # ---------- Navegación por teclado ----------

    def eventFilter(self, obj, event):
        if obj is self.search_box and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                row = min(self.results.currentRow() + 1, self.results.count() - 1)
                self.results.setCurrentRow(row)
                return True
            if key == Qt.Key_Up:
                row = max(self.results.currentRow() - 1, 0)
                self.results.setCurrentRow(row)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._activate_item(self.results.currentItem())
                return True
            if key == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    # ---------- Posicionamiento ----------

    def show_centered(self):
        win_rect = self.win.frameGeometry()
        self.adjustSize()
        x = win_rect.x() + (win_rect.width() - self.width()) // 2
        y = win_rect.y() + 100
        self.move(max(0, x), max(0, y))
        self.show()
        self.search_box.setFocus()

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim  # referencia viva para que no se corte a medias

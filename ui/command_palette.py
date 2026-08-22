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

from core.universal_search import normalize, search_catalog
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
        query = normalize(query)
        self.results.clear()

        for label, callback in self._actions:
            if not query or query in normalize(label):
                item = QListWidgetItem(f"→ {label}")
                item.setData(ROLE_RESULT, ("accion", callback))
                self.results.addItem(item)

        if query:
            available = max(0, MAX_RESULTS - self.results.count())
            matches = search_catalog(
                query,
                self.win.tv_channels_data,
                self.win.radio_stations_data,
                self.win.favorites,
                self.win.history,
                available,
            )
            for match in matches:
                prefix = "TV" if match["kind"] == "tv" else "RADIO"
                item = QListWidgetItem(f'{prefix} · {match["name"]}  —  {match["subtitle"]}')
                item.setData(ROLE_RESULT, (match["kind"], match["payload"]))
                self.results.addItem(item)

            if self.results.count() == 0:
                empty = QListWidgetItem("Sin resultados. Prueba con otro nombre, categoría o país.")
                empty.setFlags(Qt.NoItemFlags)
                self.results.addItem(empty)

        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def _activate_item(self, item: QListWidgetItem):
        if item is None:
            return
        result = item.data(ROLE_RESULT)
        if not result:
            return
        kind, payload = result
        if kind == "accion":
            self.close()
            payload()
            return
        url = payload.get("url", "") if isinstance(payload, dict) else payload.url
        name = payload.get("name", "") if isinstance(payload, dict) else payload.name
        if kind == "tv" and url:
            self.close()
            tvg_id = payload.get("tvg_id", "") if isinstance(payload, dict) else payload.tvg_id
            logo = payload.get("logo", "") if isinstance(payload, dict) else payload.logo
            self.win.playback.play(kind, name, url, tvg_id, logo)
        elif kind == "radio" and url:
            self.close()
            logo = payload.get("logo", "") if isinstance(payload, dict) else payload.favicon
            self.win.playback.play(kind, name, url, "", logo)

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

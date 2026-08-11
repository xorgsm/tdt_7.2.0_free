"""
Sidebar de Biblioteca: accesos rápidos a "Recientes" y a las carpetas de
favoritos vistas como "Playlists", estilo Spotify.

No duplica ningún dato ni lógica de filtrado propia: "Recientes" lee
directamente win.history (ya cargado y mantenido por PlaybackController /
ChannelListsController) y "Playlists" son las carpetas que ya gestiona
core/favorites.py — este panel es solo un atajo visual hacia contenido que
ya existía en Favoritos/Historial, no una fuente de datos nueva.

Panel aditivo: se inserta entre el riel de navegación (nav_rail) y el
contenido principal en _build_ui, sin sustituir nada. No importa nada de
ui.main_window (evitaría un import circular): la navegación hacia una
carpeta de favoritos concreta la resuelve MainWindow y se pasa como
callback ya hecho, igual que con CommandPalette.

Coder By X@R
"""
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from core import favorites as fav_store

ROLE_ACTION = Qt.UserRole + 70
MAX_RECENT = 8


class LibrarySidebar(QWidget):
    """Panel de biblioteca: Recientes + Playlists (carpetas de favoritos)."""

    def __init__(self, window, on_open_folder: Callable[[Optional[str]], None]):
        super().__init__()
        self.win = window
        self._on_open_folder = on_open_folder
        self.setObjectName("librarySidebar")
        self.setProperty("uiSurface", "sidebar")
        self.setFixedWidth(210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 8, 12)
        layout.setSpacing(4)

        recent_title = QLabel("RECIENTES")
        recent_title.setObjectName("libSectionTitle")
        layout.addWidget(recent_title)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("libraryRecentList")
        self.recent_list.setMaximumHeight(210)
        self.recent_list.setFrameShape(QListWidget.NoFrame)
        self.recent_list.itemClicked.connect(self._activate_recent)
        layout.addWidget(self.recent_list)

        layout.addSpacing(10)
        playlists_title = QLabel("PLAYLISTS")
        playlists_title.setObjectName("libSectionTitle")
        layout.addWidget(playlists_title)

        self.playlists_list = QListWidget()
        self.playlists_list.setObjectName("libraryPlaylistsList")
        self.playlists_list.setFrameShape(QListWidget.NoFrame)
        self.playlists_list.itemClicked.connect(self._activate_playlist)
        layout.addWidget(self.playlists_list, stretch=1)

        self.refresh()

    # ---------- Refresco ----------

    def refresh(self):
        self._refresh_recent()
        self._refresh_playlists()

    def _refresh_recent(self):
        self.recent_list.clear()
        entries = [e for e in self.win.history if e.get("url")][:MAX_RECENT]
        if not entries:
            placeholder = QListWidgetItem("Aún no hay nada reciente")
            placeholder.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(placeholder)
            return
        for entry in entries:
            icon = "TV" if entry.get("type") == "tv" else "FM"
            item = QListWidgetItem(f"{icon} · {entry.get('name', '')}")
            item.setData(ROLE_ACTION, entry)
            self.recent_list.addItem(item)

    def _refresh_playlists(self):
        self.playlists_list.clear()
        item_all = QListWidgetItem(f"★ Todos los favoritos ({len(self.win.favorites)})")
        item_all.setData(ROLE_ACTION, None)
        self.playlists_list.addItem(item_all)
        for folder in fav_store.get_folders(self.win.favorites):
            count = sum(1 for f in self.win.favorites if f.get("folder") == folder)
            item = QListWidgetItem(f"{folder} ({count})")
            item.setData(ROLE_ACTION, folder)
            self.playlists_list.addItem(item)

    # ---------- Acciones ----------

    def _activate_recent(self, item: QListWidgetItem):
        entry = item.data(ROLE_ACTION)
        if not entry or not entry.get("url"):
            return
        self.win.playback.play(
            entry.get("type", "tv"), entry.get("name", ""), entry.get("url", ""),
        )

    def _activate_playlist(self, item: QListWidgetItem):
        # "Todos los favoritos" guarda None a propósito en ROLE_ACTION: el
        # callback interpreta None como "sin filtro de carpeta".
        folder = item.data(ROLE_ACTION)
        self._on_open_folder(folder)

"""
Pestaña "Podcasts" dentro del panel de Descargas: añadir un feed RSS,
elegirlo en un desplegable, y reproducir o descargar sus episodios.

Reproducir un episodio reutiliza el mismo reproductor de audio que ya
tiene la app para radio (mismo patrón que "Enviar a la TV" desde el
historial de descargas) -- no hace falta un reproductor nuevo solo para
esto, un episodio de podcast no es distinto de una URL de audio de radio
a efectos de reproducción.

Coder By X@R
"""
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core import podcasts
from ui.fetch_worker import FetchWorker
from ui.visual import set_variant, set_visual_state


class PodcastPanel(QWidget):
    """dest_dir: carpeta donde se guardan los episodios descargados.
    on_play(url, title): callback opcional para reproducir un episodio en
    el reproductor principal de la app."""

    def __init__(self, dest_dir: str, on_play=None, parent=None):
        super().__init__(parent)
        self.setObjectName("podcastPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self.dest_dir = dest_dir
        self.on_play = on_play
        self._episodes_worker = None
        self._dl_workers = []
        self._build_ui()
        self._reload_feed_combo()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 0)
        root.setSpacing(8)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.feed_name_input = QLineEdit()
        self.feed_name_input.setObjectName("searchBox")
        self.feed_name_input.setPlaceholderText("Nombre (opcional)")
        self.feed_name_input.setFixedWidth(140)
        self.feed_url_input = QLineEdit()
        self.feed_url_input.setObjectName("searchBox")
        self.feed_url_input.setPlaceholderText("URL del feed RSS del podcast")
        self.feed_url_input.returnPressed.connect(self._on_add_feed)
        self.add_feed_btn = QPushButton("+ Añadir feed")
        set_variant(self.add_feed_btn, "primary")
        self.add_feed_btn.clicked.connect(self._on_add_feed)
        add_row.addWidget(self.feed_name_input)
        add_row.addWidget(self.feed_url_input, stretch=1)
        add_row.addWidget(self.add_feed_btn)
        root.addLayout(add_row)

        feed_row = QHBoxLayout()
        feed_row.setSpacing(6)
        lbl = QLabel("Feed:")
        lbl.setObjectName("mediaMeta")
        feed_row.addWidget(lbl)
        self.feed_combo = QComboBox()
        self.feed_combo.setObjectName("groupFilter")
        self.feed_combo.currentIndexChanged.connect(self._on_feed_selected)
        feed_row.addWidget(self.feed_combo, stretch=1)
        self.remove_feed_btn = QPushButton("Quitar feed")
        set_variant(self.remove_feed_btn, "danger")
        self.remove_feed_btn.clicked.connect(self._on_remove_feed)
        feed_row.addWidget(self.remove_feed_btn)
        root.addLayout(feed_row)

        self.status_label = QLabel("Añade un feed RSS para empezar.")
        self.status_label.setObjectName("mediaStatus")
        set_visual_state(self.status_label, "empty")
        root.addWidget(self.status_label)

        self.episode_list = QListWidget()
        self.episode_list.setObjectName("channelList")
        root.addWidget(self.episode_list, stretch=1)

    # ---------- feeds ----------

    def set_dest_dir(self, directory: str):
        self.dest_dir = directory

    def _reload_feed_combo(self):
        self.feed_combo.blockSignals(True)
        self.feed_combo.clear()
        for feed in podcasts.load_feeds():
            self.feed_combo.addItem(feed.name, feed.url)
        self.feed_combo.blockSignals(False)
        if self.feed_combo.count():
            self._load_episodes(self.feed_combo.currentData())
        else:
            self.episode_list.clear()
            self.status_label.setText("Añade un feed RSS para empezar.")

    def _on_add_feed(self):
        url = self.feed_url_input.text().strip()
        if not url:
            QMessageBox.information(self, "Falta la URL", "Pega la URL del feed RSS del podcast.")
            return
        nombre = self.feed_name_input.text().strip() or url
        podcasts.add_feed(nombre, url)
        self.feed_url_input.clear()
        self.feed_name_input.clear()
        self._reload_feed_combo()
        idx = self.feed_combo.findData(url)
        if idx >= 0:
            self.feed_combo.setCurrentIndex(idx)

    def _on_remove_feed(self):
        url = self.feed_combo.currentData()
        if not url:
            return
        podcasts.remove_feed(url)
        self._reload_feed_combo()

    def _on_feed_selected(self, _index):
        url = self.feed_combo.currentData()
        if url:
            self._load_episodes(url)

    # ---------- episodios ----------

    def _load_episodes(self, feed_url: str):
        self.status_label.setText("Cargando episodios…")
        self.episode_list.clear()
        worker = FetchWorker(podcasts.fetch_episodes, feed_url)
        worker.done.connect(self._on_episodes_loaded)
        self._episodes_worker = worker
        worker.start()

    def _on_episodes_loaded(self, episodes):
        if getattr(self.window(), "_is_closing", False):
            return
        episodes = episodes or []
        self.status_label.setText(
            f"{len(episodes)} episodios." if episodes
            else "No se encontraron episodios en ese feed (¿URL de RSS correcta?)."
        )
        for ep in episodes:
            self._add_episode_row(ep)

    def _add_episode_row(self, ep: podcasts.Episode):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(8)

        texto = ep.title
        if ep.duration:
            texto += f"  ·  {ep.duration}"
        label = QLabel(texto)
        label.setObjectName("mediaRowTitle")
        label.setWordWrap(True)
        layout.addWidget(label, stretch=1)

        if self.on_play:
            play_btn = QPushButton("▶")
            play_btn.setFixedSize(32, 26)
            play_btn.setToolTip("Reproducir")
            set_variant(play_btn, "primary")
            play_btn.clicked.connect(lambda _c=False, e=ep: self.on_play(e.audio_url, e.title))
            layout.addWidget(play_btn)

        dl_btn = QPushButton("⬇")
        dl_btn.setFixedSize(32, 26)
        dl_btn.setToolTip("Descargar")
        set_variant(dl_btn, "secondary")
        dl_btn.clicked.connect(lambda _c=False, e=ep: self._download_episode(e))
        layout.addWidget(dl_btn)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.episode_list.addItem(item)
        self.episode_list.setItemWidget(item, row)

    def _download_episode(self, ep: podcasts.Episode):
        worker = podcasts.EpisodeDownloadWorker(ep, self.dest_dir, self)
        worker.finished_ok.connect(lambda ruta: self.status_label.setText(f"Descargado: {ruta}"))
        worker.failed.connect(
            lambda msg: self.status_label.setText(
                "Descarga cancelada." if msg == "__cancelled__" else f"Error al descargar: {msg}"
            )
        )
        self._dl_workers.append(worker)
        worker.start()

    # ---------- cierre ordenado ----------

    def shutdown(self, on_wait=None):
        """Corta descargas de episodios en curso al cerrar la app."""
        for worker in self._dl_workers:
            if worker.isRunning():
                worker.cancel()
                worker.wait(2000)

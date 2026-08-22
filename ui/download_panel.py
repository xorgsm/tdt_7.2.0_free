"""
Panel 'Descargas': pega una URL y descarga el vídeo (MP4) o solo el audio (MP3).
Coder By X@R
"""
import os
import subprocess

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from core.downloader import DownloadWorker, SearchWorker, SEARCH_SOURCES, UpdateCheckWorker
from ui.audio_converter_panel import AudioConverterPanel
from ui.mp3_editor_panel import Mp3EditorPanel
from ui.mp3_tag_editor_panel import Mp3TagEditorPanel
from ui.podcast_panel import PodcastPanel
from ui.soulseek_panel import SoulseekPanel
from ui.torrent_panel import TorrentPanel
from ui.visual import set_variant, set_visual_state


class DownloadPanel(QWidget):
    """Sección de descargas: URL -> vídeo MP4 o audio MP3, vía yt-dlp;
    búsqueda de música por título/artista en YouTube/SoundCloud/música
    libre (también vía yt-dlp, ver core.downloader.SearchWorker); torrents;
    y podcasts (RSS)."""

    def __init__(self, dest_dir: str, on_dest_changed=None, on_cast=None, on_finished=None,
                 on_play_audio=None, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self.dest_dir = dest_dir
        self.on_dest_changed = on_dest_changed
        self.on_cast = on_cast
        self.on_play_audio = on_play_audio
        # Callback opcional (título, ruta) llamado al completar una
        # descarga -- pensado para que MainWindow pueda avisar por
        # bandeja aunque la ventana esté minimizada (ver
        # TrayReminderController.notify en ui/tray_controller.py). None
        # por defecto para no romper a quien construya DownloadPanel sin
        # pasarlo.
        self.on_finished = on_finished
        self._worker = None
        self._update_worker = None
        self._search_worker = None
        self._build_ui()

    # ---------- construcción ----------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mediaTabs")
        outer.addWidget(self.tabs)

        url_tab = QWidget()
        layout = QVBoxLayout(url_tab)
        layout.setContentsMargins(14, 8, 14, 0)
        layout.setSpacing(8)

        # ── Fila 1: URL + formato + descargar + cancelar ──────────────────
        url_row = QHBoxLayout()
        url_row.setSpacing(6)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("searchBox")
        self.url_input.setPlaceholderText("Pega aquí la URL del vídeo (YouTube, etc.)")
        self.url_input.setFixedHeight(34)
        self.url_input.returnPressed.connect(self._start_download)
        url_row.addWidget(self.url_input, stretch=1)

        self.format_combo = QComboBox()
        self.format_combo.setObjectName("groupFilter")
        self.format_combo.addItem("MP4", "mp4")
        self.format_combo.addItem("MP3", "mp3")
        self.format_combo.setFixedWidth(90)
        self.format_combo.setFixedHeight(34)
        url_row.addWidget(self.format_combo)

        self.download_btn = QPushButton("Descargar")
        self.download_btn.setObjectName("mediaPrimaryButton")
        set_variant(self.download_btn, "primary")
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setFixedHeight(34)
        self.download_btn.clicked.connect(self._start_download)
        url_row.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setObjectName("mediaDangerButton")
        set_variant(self.cancel_btn, "danger")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFixedSize(34, 34)
        self.cancel_btn.setToolTip("Cancelar la descarga")
        self.cancel_btn.clicked.connect(self._cancel_download)
        self.cancel_btn.setVisible(False)
        url_row.addWidget(self.cancel_btn)

        layout.addLayout(url_row)

        # ── Buscar música por título/artista (YouTube/SoundCloud/CC) ──────
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchBox")
        self.search_input.setPlaceholderText("...o busca una canción o artista")
        self.search_input.setFixedHeight(30)
        self.search_input.returnPressed.connect(self._start_search)
        search_row.addWidget(self.search_input, stretch=1)

        self.source_combo = QComboBox()
        self.source_combo.setObjectName("groupFilter")
        for fuente in SEARCH_SOURCES:
            self.source_combo.addItem(fuente, fuente)
        self.source_combo.setFixedWidth(120)
        self.source_combo.setFixedHeight(30)
        search_row.addWidget(self.source_combo)

        self.search_btn = QPushButton("Buscar")
        set_variant(self.search_btn, "secondary")
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setFixedHeight(30)
        self.search_btn.clicked.connect(self._start_search)
        search_row.addWidget(self.search_btn)

        self.search_cancel_btn = QPushButton("✕")
        set_variant(self.search_cancel_btn, "danger")
        self.search_cancel_btn.setCursor(Qt.PointingHandCursor)
        self.search_cancel_btn.setFixedSize(30, 30)
        self.search_cancel_btn.setToolTip("Cancelar la búsqueda")
        self.search_cancel_btn.clicked.connect(self._cancel_search)
        self.search_cancel_btn.setVisible(False)  # solo mientras hay una búsqueda en curso
        search_row.addWidget(self.search_cancel_btn)

        layout.addLayout(search_row)

        # Oculta hasta la primera búsqueda: no ocupar espacio de la pestaña
        # mientras solo se está pegando una URL directa, el uso más común.
        self.search_results_list = QListWidget()
        self.search_results_list.setObjectName("channelList")
        self.search_results_list.setMaximumHeight(170)
        self.search_results_list.setVisible(False)
        layout.addWidget(self.search_results_list)

        # ── Fila 2: carpeta + cambiar + abrir + actualizar yt-dlp ─────────
        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)

        lbl = QLabel("Carpeta:")
        lbl.setObjectName("mediaMeta")
        dest_row.addWidget(lbl)

        self.dest_label = QLabel()
        self.dest_label.setObjectName("mediaPath")
        self.dest_label.setMaximumWidth(320)
        self._set_dest_label_text(self.dest_dir)
        dest_row.addWidget(self.dest_label, stretch=1)

        anchos = {"Cambiar": 72, "Abrir": 60, "Actualizar": 110}
        for texto, tooltip, accion in (
            ("Cambiar",    "Cambiar carpeta de descargas",         self._change_dest),
            ("Abrir",      "Abrir carpeta en el explorador",       lambda: self._open_folder(self.dest_dir)),
            ("Actualizar", "Comprobar actualización de yt-dlp",   self._force_update_check),
        ):
            btn = QPushButton(texto)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setFixedWidth(anchos[texto])
            btn.setToolTip(tooltip)
            set_variant(btn, "secondary")
            btn.clicked.connect(accion)
            dest_row.addWidget(btn)
            if texto == "Actualizar":
                self.update_btn = btn

        layout.addLayout(dest_row)

        # ── Barra de progreso ──────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("mediaProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFixedHeight(16)
        layout.addWidget(self.progress_bar)

        # ── Estado ────────────────────────────────────────────────────────
        self.status_label = QLabel("Listo.")
        self.status_label.setObjectName("mediaStatus")
        set_visual_state(self.status_label, "default")
        layout.addWidget(self.status_label)

        # ── Historial ─────────────────────────────────────────────────────
        lbl_hist = QLabel("Descargas recientes")
        lbl_hist.setObjectName("mediaSection")
        layout.addWidget(lbl_hist)

        self.history_list = QListWidget()
        self.history_list.setObjectName("channelList")
        self.history_list.itemDoubleClicked.connect(self._on_history_double_click)
        layout.addWidget(self.history_list, stretch=1)

        self.tabs.addTab(url_tab, "Vídeo (URL)")

        self.torrent_panel = TorrentPanel(self.dest_dir, on_dest_changed=self._on_torrent_dest_changed)
        self.tabs.addTab(self.torrent_panel, "Torrents")

        self.podcast_panel = PodcastPanel(self.dest_dir, on_play=self.on_play_audio)
        self.tabs.addTab(self.podcast_panel, "Podcasts")

        self.soulseek_panel = SoulseekPanel(self.dest_dir, on_dest_changed=self._on_soulseek_dest_changed)
        self.tabs.addTab(self.soulseek_panel, "Soulseek")

        self.audio_converter_panel = AudioConverterPanel(
            self.dest_dir, on_dest_changed=self._on_converter_dest_changed
        )
        self.tabs.addTab(self.audio_converter_panel, "Convertir")

        self.mp3_editor_panel = Mp3EditorPanel()
        self.tabs.addTab(self.mp3_editor_panel, "Editor MP3")

        self.mp3_tag_editor_panel = Mp3TagEditorPanel()
        self.tabs.addTab(self.mp3_tag_editor_panel, "Editar info")

    # ---------- carpeta destino ----------

    def _set_dest_label_text(self, directory: str):
        """Elide la ruta al ancho máximo del label -- una ruta larga sin
        elidir fuerza el sizeHint natural del QLabel (que no recorta solo
        por tener maximumWidth) y desborda la fila de botones en ventanas
        estrechas."""
        metrics = QFontMetrics(self.dest_label.font())
        elidido = metrics.elidedText(directory, Qt.ElideMiddle, self.dest_label.maximumWidth())
        self.dest_label.setText(elidido)
        self.dest_label.setToolTip(directory)

    def _change_dest(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Selecciona carpeta de descargas", self.dest_dir
        )
        if directory:
            self.dest_dir = directory
            self._set_dest_label_text(directory)
            self.torrent_panel.set_dest_dir(directory)
            self.podcast_panel.set_dest_dir(directory)
            self.soulseek_panel.set_dest_dir(directory)
            self.audio_converter_panel.set_dest_dir(directory)
            if self.on_dest_changed:
                self.on_dest_changed(directory)

    def _on_torrent_dest_changed(self, directory: str):
        """Espejo de _change_dest, pero disparado desde la pestaña de
        Torrents — mantiene la carpeta sincronizada en los dos sentidos."""
        self.dest_dir = directory
        self._set_dest_label_text(directory)
        self.podcast_panel.set_dest_dir(directory)
        if self.on_dest_changed:
            self.on_dest_changed(directory)

    def _on_soulseek_dest_changed(self, directory: str):
        self.dest_dir = directory
        self._set_dest_label_text(directory)
        if self.on_dest_changed:
            self.on_dest_changed(directory)

    def _on_converter_dest_changed(self, directory: str):
        self.dest_dir = directory
        self._set_dest_label_text(directory)
        if self.on_dest_changed:
            self.on_dest_changed(directory)

    def _open_folder(self, path: str):
        """Abre 'path' en el explorador; si es un archivo, lo deja seleccionado."""
        if os.path.isfile(path):
            if os.name == "nt":
                try:
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
                    return
                except OSError:
                    pass
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        elif os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(
                self, "No encontrado", "Esa carpeta o archivo ya no existe."
            )

    # ---------- descarga ----------

    def _start_download(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Descarga en curso", "Espera a que termine la descarga actual."
            )
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.information(
                self, "Falta la URL", "Pega la URL del vídeo que quieres descargar."
            )
            return

        as_mp3 = self.format_combo.currentData() == "mp3"
        self._set_busy(True)
        self.progress_bar.setValue(0)
        self._set_status("Iniciando descarga…")

        self._worker = DownloadWorker(url, self.dest_dir, as_mp3, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(lambda dest: self._on_finished(url, dest, as_mp3))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_busy(self, ocupado: bool):
        """Único punto que decide el estado visual del panel durante una descarga."""
        self.download_btn.setEnabled(not ocupado)
        self.download_btn.setText("Descargando…" if ocupado else "⬇  Descargar")
        self.cancel_btn.setVisible(ocupado)
        self.cancel_btn.setEnabled(ocupado)
        self.url_input.setReadOnly(ocupado)
        self.format_combo.setEnabled(not ocupado)

    def _set_status(self, texto: str, error: bool = False):
        self.status_label.setText(texto)
        set_visual_state(self.status_label, "error" if error else "default")

    def _cancel_download(self):
        if self._worker is None or not self._worker.isRunning():
            return
        self.cancel_btn.setEnabled(False)
        self._set_status("Cancelando…")
        self._worker.cancel()

    def _on_progress(self, frac: float, texto: str):
        self.progress_bar.setValue(int(frac * 100))
        self.status_label.setText(texto)

    def _on_finished(self, url: str, result_path: str, as_mp3: bool):
        self._set_busy(False)
        self.progress_bar.setValue(100)

        es_archivo = bool(result_path) and os.path.isfile(result_path)
        self._set_status(f"Completado → {result_path}")

        icono = "🎵" if as_mp3 else "🎬"
        if es_archivo:
            nombre = os.path.basename(result_path)
            self._add_history_row(nombre, icono, result_path)
        else:
            nombre = url
            self._add_history_row(url, icono, None)
        self.url_input.clear()

        if self.on_finished:
            self.on_finished(nombre, result_path if es_archivo else "")

    def _add_history_row(self, texto: str, icono: str, filepath: str | None):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 4, 6, 4)
        row_layout.setSpacing(8)

        label = QLabel(f"{icono}  {texto}")
        label.setObjectName("mediaRowTitle")
        row_layout.addWidget(label, stretch=1)

        if filepath and self.on_cast:
            cast_btn = QPushButton("TV")
            cast_btn.setFixedHeight(26)
            cast_btn.setFixedWidth(42)
            cast_btn.setCursor(Qt.PointingHandCursor)
            cast_btn.setToolTip("Enviar a la TV (Chromecast)")
            set_variant(cast_btn, "cast")
            cast_btn.clicked.connect(
                lambda: self.on_cast(filepath, os.path.basename(filepath))
            )
            row_layout.addWidget(cast_btn)

        if filepath:
            open_btn = QPushButton("Abrir")
            open_btn.setFixedHeight(26)
            open_btn.setFixedWidth(56)
            open_btn.setCursor(Qt.PointingHandCursor)
            open_btn.setToolTip("Ver en la carpeta del explorador")
            set_variant(open_btn, "secondary")
            open_btn.clicked.connect(lambda: self._open_folder(filepath))
            row_layout.addWidget(open_btn)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        if filepath:
            item.setData(Qt.UserRole, filepath)
        self.history_list.insertItem(0, item)
        self.history_list.setItemWidget(item, row)

    def _on_history_double_click(self, item: QListWidgetItem):
        ruta = item.data(Qt.UserRole)
        if not ruta:
            return
        if os.path.isfile(ruta):
            QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
        else:
            QMessageBox.information(
                self, "No encontrado", "Ese archivo ya no está en su ubicación original."
            )

    def _on_failed(self, mensaje: str):
        self._set_busy(False)
        self.progress_bar.setValue(0)
        if mensaje == "__cancelled__":
            self._set_status("Descarga cancelada.")
            return
        self._set_status("Error en la descarga.", error=True)
        QMessageBox.warning(self, "Error al descargar", mensaje)

    # ---------- búsqueda de música ----------

    def _start_search(self):
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        query = self.search_input.text().strip()
        if not query:
            return

        self.search_btn.setEnabled(False)
        self.search_btn.setText("Buscando…")
        self.search_cancel_btn.setVisible(True)
        self.search_cancel_btn.setEnabled(True)
        self.search_results_list.clear()
        self.search_results_list.setVisible(True)
        self._set_status(f"Buscando «{query}»…")

        fuente = self.source_combo.currentData()
        self._search_worker = SearchWorker(query, fuente, self)
        self._search_worker.results.connect(self._on_search_results)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    def _cancel_search(self):
        if self._search_worker is None or not self._search_worker.isRunning():
            return
        self.search_cancel_btn.setEnabled(False)
        self._set_status("Cancelando búsqueda…")
        self._search_worker.cancel()

    def _on_search_results(self, resultados: list):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("Buscar")
        self.search_cancel_btn.setVisible(False)
        self.search_results_list.clear()

        if not resultados:
            self._set_status("Sin resultados para esa búsqueda.")
            item = QListWidgetItem("Sin resultados para esa búsqueda.")
            item.setFlags(Qt.NoItemFlags)
            self.search_results_list.addItem(item)
            return

        self._set_status(f"{len(resultados)} resultado(s).")
        for resultado in resultados:
            self._add_search_result_row(resultado)

    def _on_search_failed(self, mensaje: str):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("Buscar")
        self.search_cancel_btn.setVisible(False)
        if mensaje == "__cancelled__":
            self._set_status("Búsqueda cancelada.")
            return
        self._set_status("Error en la búsqueda.", error=True)
        QMessageBox.warning(self, "Error al buscar", mensaje)

    def _add_search_result_row(self, resultado: dict):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 4, 6, 4)
        row_layout.setSpacing(8)

        texto = (
            f"{resultado['title']}  —  {resultado['artist']}  ·  "
            f"{resultado['duration']}  ·  {resultado['source']}"
        )
        label = QLabel(texto)
        label.setObjectName("mediaRowTitle")
        label.setWordWrap(True)
        row_layout.addWidget(label, stretch=1)

        dl_btn = QPushButton("⬇ MP3")
        dl_btn.setFixedHeight(26)
        dl_btn.setFixedWidth(64)
        dl_btn.setCursor(Qt.PointingHandCursor)
        dl_btn.setToolTip("Descargar como MP3")
        set_variant(dl_btn, "primary")
        dl_btn.clicked.connect(lambda: self._download_search_result(resultado["url"]))
        row_layout.addWidget(dl_btn)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.search_results_list.addItem(item)
        self.search_results_list.setItemWidget(item, row)

    def _download_search_result(self, url: str):
        # Resultados de búsqueda son música -> siempre MP3, sin obligar al
        # usuario a tocar el selector de formato pensado para la URL directa.
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Descarga en curso", "Espera a que termine la descarga actual."
            )
            return
        self.url_input.setText(url)
        indice_mp3 = self.format_combo.findData("mp3")
        if indice_mp3 >= 0:
            self.format_combo.setCurrentIndex(indice_mp3)
        self._start_download()

    # ---------- actualización manual de yt-dlp ----------

    def _force_update_check(self):
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Comprobando…")
        self._update_worker = UpdateCheckWorker(self)
        self._update_worker.done.connect(self._on_update_checked)
        self._update_worker.start()

    def _on_update_checked(self, ok: bool, mensaje: str):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Actualizar")
        self._set_status(mensaje, error=not ok)

    # ---------- cierre ordenado ----------

    def shutdown(self, on_wait=None):
        """
        Corta cualquier descarga en curso al cerrar la aplicación. Sin esto,
        el proceso yt-dlp.exe seguiría vivo en segundo plano después de cerrar
        la ventana, descargando y ocupando disco sin que nadie lo vea.

        on_wait: se reenvía tal cual hasta TorrentClient.cerrar() por
        compatibilidad con su firma anterior (cuando aria2c.exe corría
        aparte y había que esperar su apagado) -- con libtorrent en el
        propio proceso, cerrar() ya no bloquea, así que no hace falta.
        """
        for worker in (self._worker, self._update_worker, self._search_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.wait(3000)
        self.podcast_panel.shutdown()
        self.torrent_panel.shutdown(on_wait=on_wait)
        self.soulseek_panel.shutdown(on_wait=on_wait)
        self.audio_converter_panel.shutdown(on_wait=on_wait)
        self.mp3_editor_panel.shutdown(on_wait=on_wait)
        self.mp3_tag_editor_panel.shutdown(on_wait=on_wait)

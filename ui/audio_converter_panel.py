"""
Pestaña "Convertir" dentro del panel de Descargas: convierte archivos de
audio (ver core.audio_converter.INPUT_EXTENSIONS para la lista completa
de formatos soportados) a MP3 (320kbps) usando ffmpeg. Solo en la versión
con licencia (ver ui/download_panel.py).

Coder By X@R
"""
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from core.audio_converter import INPUT_EXTENSIONS, AudioConvertWorker
from ui.visual import set_variant, set_visual_state


class AudioConverterPanel(QWidget):
    """dest_dir: carpeta donde se guardan los MP3 convertidos."""

    def __init__(self, dest_dir: str, on_dest_changed=None, parent=None):
        super().__init__(parent)
        self.setObjectName("audioConverterPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self.dest_dir = dest_dir
        self.on_dest_changed = on_dest_changed
        self._pending_paths: list = []
        self._worker = None
        self._build_ui()

    # ---------- construcción ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 0)
        layout.setSpacing(8)

        # ── Añadir / quitar archivos ────────────────────────────────────
        add_row = QHBoxLayout()
        add_row.setSpacing(6)

        add_btn = QPushButton("+ Añadir archivos")
        set_variant(add_btn, "primary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_files)
        add_row.addWidget(add_btn)

        remove_btn = QPushButton("Quitar seleccionado")
        set_variant(remove_btn, "secondary")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._on_remove_selected)
        add_row.addWidget(remove_btn)

        clear_btn = QPushButton("Vaciar lista")
        set_variant(clear_btn, "danger")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear_list)
        add_row.addWidget(clear_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        self.pending_list = QListWidget()
        self.pending_list.setObjectName("channelList")
        self.pending_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.pending_list.setMaximumHeight(140)
        layout.addWidget(self.pending_list)

        # ── Carpeta destino ──────────────────────────────────────────────
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

        change_btn = QPushButton("Cambiar")
        change_btn.setCursor(Qt.PointingHandCursor)
        change_btn.setFixedWidth(72)
        set_variant(change_btn, "secondary")
        change_btn.clicked.connect(self._change_dest)
        dest_row.addWidget(change_btn)

        open_btn = QPushButton("Abrir")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFixedWidth(60)
        set_variant(open_btn, "secondary")
        open_btn.clicked.connect(lambda: self._open_folder(self.dest_dir))
        dest_row.addWidget(open_btn)

        layout.addLayout(dest_row)

        # ── Convertir / cancelar ─────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.convert_btn = QPushButton("Convertir")
        set_variant(self.convert_btn, "primary")
        self.convert_btn.setCursor(Qt.PointingHandCursor)
        self.convert_btn.clicked.connect(self._start_conversion)
        action_row.addWidget(self.convert_btn)

        self.cancel_btn = QPushButton("✕")
        set_variant(self.cancel_btn, "danger")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFixedSize(34, 34)
        self.cancel_btn.setToolTip("Cancelar la conversión")
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.cancel_btn.setVisible(False)
        action_row.addWidget(self.cancel_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        # ── Progreso / estado ─────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("mediaProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFixedHeight(16)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel(
            "Añade archivos de audio (WAV, FLAC, AIFF, OGG, M4A, Opus, WebM...) "
            "para convertir a MP3 (320kbps)."
        )
        self.status_label.setObjectName("mediaStatus")
        set_visual_state(self.status_label, "empty")
        layout.addWidget(self.status_label)

        # ── Convertidos recientes ─────────────────────────────────────────
        lbl_hist = QLabel("Convertidos recientes")
        lbl_hist.setObjectName("mediaSection")
        layout.addWidget(lbl_hist)

        self.history_list = QListWidget()
        self.history_list.setObjectName("channelList")
        layout.addWidget(self.history_list, stretch=1)

    # ---------- lista de pendientes ----------

    def _on_add_files(self):
        patrones = " ".join(f"*{ext}" for ext in INPUT_EXTENSIONS)
        filtro = f"Audio ({patrones})"
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecciona archivos de audio", self.dest_dir, filtro
        )
        for path in paths:
            if path.lower().endswith(INPUT_EXTENSIONS) and path not in self._pending_paths:
                self._pending_paths.append(path)
                self.pending_list.addItem(QListWidgetItem(os.path.basename(path)))
        self._update_status_idle()

    def _on_remove_selected(self):
        for item in self.pending_list.selectedItems():
            idx = self.pending_list.row(item)
            self.pending_list.takeItem(idx)
            del self._pending_paths[idx]
        self._update_status_idle()

    def _on_clear_list(self):
        self._pending_paths.clear()
        self.pending_list.clear()
        self._update_status_idle()

    def _update_status_idle(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._pending_paths:
            self.status_label.setText(f"{len(self._pending_paths)} archivo(s) listo(s) para convertir.")
            set_visual_state(self.status_label, "default")
        else:
            self.status_label.setText(
                "Añade archivos de audio (WAV, FLAC, AIFF, OGG, M4A, Opus, WebM...) "
                "para convertir a MP3 (320kbps)."
            )
            set_visual_state(self.status_label, "empty")

    # ---------- carpeta destino ----------

    def _set_dest_label_text(self, directory: str):
        metrics = QFontMetrics(self.dest_label.font())
        elidido = metrics.elidedText(directory, Qt.ElideMiddle, self.dest_label.maximumWidth())
        self.dest_label.setText(elidido)
        self.dest_label.setToolTip(directory)

    def set_dest_dir(self, directory: str):
        self.dest_dir = directory
        self._set_dest_label_text(directory)

    def _change_dest(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Selecciona carpeta de destino", self.dest_dir
        )
        if directory:
            self.dest_dir = directory
            self._set_dest_label_text(directory)
            if self.on_dest_changed:
                self.on_dest_changed(directory)

    def _open_folder(self, path: str):
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "No encontrado", "Esa carpeta ya no existe.")

    # ---------- conversión ----------

    def _start_conversion(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._pending_paths:
            QMessageBox.information(
                self, "Nada que convertir", "Añade al menos un archivo de audio."
            )
            return

        self._set_busy(True)
        self.progress_bar.setValue(0)
        total = len(self._pending_paths)

        self._worker = AudioConvertWorker(list(self._pending_paths), self.dest_dir, self)
        self._worker.progress.connect(lambda idx, tot, nombre: self._on_progress(idx, tot, nombre))
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.finished_all.connect(self._on_finished_all)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()
        self._total_actual = total

    def _set_busy(self, ocupado: bool):
        self.convert_btn.setEnabled(not ocupado)
        self.convert_btn.setText("Convirtiendo…" if ocupado else "Convertir")
        self.cancel_btn.setVisible(ocupado)
        self.cancel_btn.setEnabled(ocupado)

    def _cancel_conversion(self):
        if self._worker is None or not self._worker.isRunning():
            return
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelando…")
        self._worker.cancel()

    def _on_progress(self, idx: int, total: int, nombre: str):
        self.progress_bar.setValue(int(idx / total * 100) if total else 0)
        self.status_label.setText(f"Convirtiendo {idx + 1}/{total}: {nombre}")
        set_visual_state(self.status_label, "default")

    def _on_file_done(self, input_path: str, output_path: str):
        self._add_history_row(os.path.basename(output_path), output_path)

    def _on_file_failed(self, input_path: str, mensaje: str):
        self._add_history_row(f"Error: {os.path.basename(input_path)} — {mensaje}", None)

    def _on_finished_all(self):
        self.progress_bar.setValue(100)
        self._set_busy(False)
        self._on_clear_list()
        self.status_label.setText("Conversión completada.")
        set_visual_state(self.status_label, "default")

    def _on_cancelled(self):
        self._set_busy(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Conversión cancelada.")
        set_visual_state(self.status_label, "default")

    def _add_history_row(self, texto: str, filepath: str | None):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 4, 6, 4)
        row_layout.setSpacing(8)

        icono = "🎵" if filepath else "⚠"
        label = QLabel(f"{icono}  {texto}")
        label.setObjectName("mediaRowTitle")
        label.setWordWrap(True)
        row_layout.addWidget(label, stretch=1)

        if filepath:
            open_btn = QPushButton("Abrir")
            open_btn.setFixedHeight(26)
            open_btn.setFixedWidth(56)
            open_btn.setCursor(Qt.PointingHandCursor)
            set_variant(open_btn, "secondary")
            open_btn.clicked.connect(lambda: self._open_folder(os.path.dirname(filepath)))
            row_layout.addWidget(open_btn)

        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.history_list.insertItem(0, item)
        self.history_list.setItemWidget(item, row)

    # ---------- cierre ordenado ----------

    def shutdown(self, on_wait=None):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)

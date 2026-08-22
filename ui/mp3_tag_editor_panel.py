"""
Pestaña "Editar info" dentro del panel de Descargas: ver y editar los tags
ID3 (título, artista, álbum, año, género, pista) de un MP3. Solo en la
versión con licencia (ver ui/download_panel.py).

Coder By X@R
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core import mp3_info
from core.mp3_info import Mp3TagWriteWorker
from ui.fetch_worker import FetchWorker, shutdown_workers
from ui.visual import set_variant, set_visual_state


class Mp3TagEditorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mp3TagEditorPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self._paths: list = []
        self._probe_workers: list = []
        self._write_worker = None
        self._loading_path: "str | None" = None  # evita pisar el formulario con un probe ya obsoleto
        self._saving_path: "str | None" = None
        self._build_ui()

    # ---------- construcción ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 0)
        layout.setSpacing(8)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)

        add_btn = QPushButton("+ Añadir MP3")
        set_variant(add_btn, "primary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_files)
        add_row.addWidget(add_btn)

        remove_btn = QPushButton("Quitar de la lista")
        set_variant(remove_btn, "danger")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._on_remove_selected)
        add_row.addWidget(remove_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        self.file_list = QListWidget()
        self.file_list.setObjectName("channelList")
        self.file_list.setMaximumHeight(160)
        self.file_list.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self.file_list)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 4, 0, 4)
        form.setSpacing(6)
        self._fields: dict = {}
        for clave, etiqueta in mp3_info.TAG_FIELDS:
            campo = QLineEdit()
            campo.setObjectName("searchBox")
            campo.setEnabled(False)
            form.addRow(f"{etiqueta}:", campo)
            self._fields[clave] = campo
        layout.addWidget(form_widget)

        save_row = QHBoxLayout()
        save_row.setSpacing(6)
        self.save_btn = QPushButton("Guardar")
        set_variant(self.save_btn, "primary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.status_label = QLabel("Añade uno o varios MP3 para ver y editar su información.")
        self.status_label.setObjectName("mediaStatus")
        set_visual_state(self.status_label, "empty")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    # ---------- lista de archivos ----------

    def _on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecciona archivos MP3", "", "Audio MP3 (*.mp3)"
        )
        for path in paths:
            if path not in self._paths:
                self._paths.append(path)
                self.file_list.addItem(QListWidgetItem(os.path.basename(path)))
        if paths and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)

    def _on_remove_selected(self):
        idx = self.file_list.currentRow()
        if idx < 0:
            return
        self.file_list.takeItem(idx)
        del self._paths[idx]
        if not self._paths:
            self._clear_form()

    def _current_path(self) -> "str | None":
        idx = self.file_list.currentRow()
        if 0 <= idx < len(self._paths):
            return self._paths[idx]
        return None

    # ---------- carga de tags ----------

    def _on_selection_changed(self, _row: int):
        path = self._current_path()
        if path is None:
            self._clear_form()
            return
        self._clear_form()
        self.status_label.setText(f"Leyendo información de {os.path.basename(path)}…")
        set_visual_state(self.status_label, "default")
        self._loading_path = path
        worker = FetchWorker(mp3_info.probe, path)
        worker.done.connect(lambda info, p=path: self._on_probed(p, info))
        # Sin esto la lista solo crece: cada cambio de selección deja su
        # FetchWorker ya terminado colgado en memoria hasta cerrar el panel.
        worker.finished.connect(
            lambda w=worker: self._probe_workers.remove(w) if w in self._probe_workers else None,
            Qt.QueuedConnection,
        )
        self._probe_workers.append(worker)
        worker.start()

    def _on_probed(self, path: str, info: "dict | None"):
        if path != self._loading_path or path != self._current_path():
            return  # la selección cambió mientras el probe estaba en curso
        tags = (info or {}).get("tags", {})
        for clave, campo in self._fields.items():
            campo.setText(tags.get(clave, ""))
            campo.setEnabled(True)
        self.save_btn.setEnabled(True)
        if tags:
            self.status_label.setText(f"Información cargada: {os.path.basename(path)}")
        else:
            self.status_label.setText(
                f"{os.path.basename(path)} no tiene tags (o no se pudieron leer) -- puedes añadirlos y guardar."
            )
        set_visual_state(self.status_label, "default")

    def _clear_form(self):
        self._loading_path = None
        for campo in self._fields.values():
            campo.clear()
            campo.setEnabled(False)
        self.save_btn.setEnabled(False)
        if not self._paths:
            self.status_label.setText("Añade uno o varios MP3 para ver y editar su información.")
            set_visual_state(self.status_label, "empty")

    # ---------- guardado ----------

    def _on_save(self):
        path = self._current_path()
        if path is None:
            return
        if self._write_worker is not None and self._write_worker.isRunning():
            return

        tags = {clave: campo.text().strip() for clave, campo in self._fields.items()}
        self._saving_path = path
        self.save_btn.setEnabled(False)
        self.status_label.setText("Guardando…")
        set_visual_state(self.status_label, "default")

        self._write_worker = Mp3TagWriteWorker(path, tags, self)
        self._write_worker.finished_ok.connect(self._on_save_done)
        self._write_worker.failed.connect(self._on_save_failed)
        self._write_worker.start()

    def _sync_save_button_state(self):
        """Recalcula si 'Guardar' debe estar habilitado a partir de la
        selección ACTUAL -- nunca lo pone en True a ciegas al terminar un
        guardado, porque el usuario pudo cambiar de archivo mientras tanto
        (y ese nuevo archivo puede seguir con su propio probe en curso)."""
        self.save_btn.setEnabled(
            self._current_path() is not None and self._loading_path is None
        )

    def _on_save_done(self, path: str):
        self._saving_path = None
        self.status_label.setText(f"Guardado: {os.path.basename(path)}")
        set_visual_state(self.status_label, "default")
        self._sync_save_button_state()

    def _on_save_failed(self, mensaje: str):
        self._saving_path = None
        if mensaje == "__cancelled__":
            self.status_label.setText("Guardado cancelado.")
            set_visual_state(self.status_label, "default")
            self._sync_save_button_state()
            return
        self._sync_save_button_state()
        self.status_label.setText("Error al guardar la información.")
        set_visual_state(self.status_label, "error")
        QMessageBox.warning(self, "Error al guardar", mensaje)

    # ---------- cierre ordenado ----------

    def shutdown(self, on_wait=None):
        shutdown_workers(self._probe_workers)
        if self._write_worker is not None and self._write_worker.isRunning():
            self._write_worker.cancel()
            self._write_worker.wait(5000)

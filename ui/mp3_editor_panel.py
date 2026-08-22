"""
Pestaña "Editor MP3" dentro del panel de Descargas: recorta y une varios
MP3 en uno solo, con fundido cruzado entre cada unión para que no se note
el corte ni un salto de volumen. Solo en la versión con licencia (ver
ui/download_panel.py).

Coder By X@R
"""
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from core import mp3_info
from core.audio_editor import (
    DEFAULT_FADE_SECONDS, MAX_FADE_SECONDS, MIN_FADE_SECONDS,
    AudioEditWorker, Segment,
)
from player.audio_preview import AudioPreviewPlayer
from ui.fetch_worker import FetchWorker, shutdown_workers
from ui.visual import set_variant, set_visual_state

_PREVIEW_POLL_MS = 200


def _fmt_ms(ms: "int | None") -> str:
    if ms is None:
        return "--:--"
    total_s = ms // 1000
    return f"{total_s // 60}:{total_s % 60:02d}"


class _Item:
    __slots__ = ("path", "start_ms", "end_ms", "duration_ms")

    def __init__(self, path: str):
        self.path = path
        self.start_ms: "int | None" = None
        self.end_ms: "int | None" = None
        self.duration_ms: "int | None" = None


class Mp3EditorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mp3EditorPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self._items: list = []
        self._worker = None
        self._preview = AudioPreviewPlayer(self)
        self._preview.error_occurred.connect(self._on_preview_error)
        self._preview.end_reached.connect(self._on_preview_end)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_PREVIEW_POLL_MS)
        self._poll_timer.timeout.connect(self._on_poll_preview)
        self._preview_loaded_path: "str | None" = None
        self._probe_workers: list = []
        self._build_ui()

    # ---------- construcción ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 0)
        layout.setSpacing(8)

        # ── Añadir / quitar / reordenar ────────────────────────────────
        add_row = QHBoxLayout()
        add_row.setSpacing(6)

        add_btn = QPushButton("+ Añadir MP3")
        set_variant(add_btn, "primary")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_files)
        add_row.addWidget(add_btn)

        up_btn = QPushButton("▲ Subir")
        set_variant(up_btn, "secondary")
        up_btn.setCursor(Qt.PointingHandCursor)
        up_btn.clicked.connect(self._on_move_up)
        add_row.addWidget(up_btn)

        down_btn = QPushButton("▼ Bajar")
        set_variant(down_btn, "secondary")
        down_btn.setCursor(Qt.PointingHandCursor)
        down_btn.clicked.connect(self._on_move_down)
        add_row.addWidget(down_btn)

        remove_btn = QPushButton("Quitar")
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

        # ── Vista previa del archivo seleccionado ─────────────────────────
        preview_row = QHBoxLayout()
        preview_row.setSpacing(6)

        self.play_btn = QPushButton("▶")
        set_variant(self.play_btn, "primary")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setFixedWidth(40)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._on_play_pause)
        preview_row.addWidget(self.play_btn)

        self.position_label = QLabel("--:-- / --:--")
        self.position_label.setObjectName("mediaMeta")
        preview_row.addWidget(self.position_label)

        mark_start_btn = QPushButton("Marcar inicio")
        set_variant(mark_start_btn, "secondary")
        mark_start_btn.setCursor(Qt.PointingHandCursor)
        mark_start_btn.clicked.connect(self._on_mark_start)
        preview_row.addWidget(mark_start_btn)

        mark_end_btn = QPushButton("Marcar fin")
        set_variant(mark_end_btn, "secondary")
        mark_end_btn.setCursor(Qt.PointingHandCursor)
        mark_end_btn.clicked.connect(self._on_mark_end)
        preview_row.addWidget(mark_end_btn)

        reset_btn = QPushButton("Quitar recorte")
        set_variant(reset_btn, "ghost")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._on_reset_trim)
        preview_row.addWidget(reset_btn)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

        self.marks_label = QLabel("Selecciona un archivo de la lista para recortarlo.")
        self.marks_label.setObjectName("mediaMeta")
        layout.addWidget(self.marks_label)

        # ── Fundido + unir ──────────────────────────────────────────────
        join_row = QHBoxLayout()
        join_row.setSpacing(6)

        lbl_fade = QLabel("Fundido:")
        lbl_fade.setObjectName("mediaMeta")
        join_row.addWidget(lbl_fade)

        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(MIN_FADE_SECONDS, MAX_FADE_SECONDS)
        self.fade_spin.setSingleStep(0.5)
        self.fade_spin.setValue(DEFAULT_FADE_SECONDS)
        self.fade_spin.setSuffix(" s")
        self.fade_spin.setFixedWidth(90)
        join_row.addWidget(self.fade_spin)

        self.join_btn = QPushButton("Unir")
        set_variant(self.join_btn, "primary")
        self.join_btn.setCursor(Qt.PointingHandCursor)
        self.join_btn.clicked.connect(self._on_join)
        join_row.addWidget(self.join_btn)

        self.cancel_btn = QPushButton("✕")
        set_variant(self.cancel_btn, "danger")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFixedSize(34, 34)
        self.cancel_btn.setToolTip("Cancelar la unión")
        self.cancel_btn.clicked.connect(self._on_cancel_join)
        self.cancel_btn.setVisible(False)
        join_row.addWidget(self.cancel_btn)
        join_row.addStretch(1)
        layout.addLayout(join_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("mediaProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel(
            "Añade al menos dos MP3, márcales inicio/fin (opcional) y pulsa Unir."
        )
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
            item = _Item(path)
            self._items.append(item)
            self.file_list.addItem(QListWidgetItem(os.path.basename(path)))
            self._probe_duration(item)
        self._update_status_idle()

    def _probe_duration(self, item: "_Item"):
        """Lee la duración del archivo en segundo plano (ffmpeg -i, ver
        core/mp3_info.py) nada más añadirlo -- así "Fin" sin marcar puede
        mostrar la duración real, y _expected_total_ms() puede estimar el
        % de avance de la unión sin obligar a reproducir cada archivo antes."""
        worker = FetchWorker(mp3_info.probe, item.path)
        worker.done.connect(lambda info, it=item: self._on_duration_probed(it, info))
        # Sin esto la lista solo crece: cada archivo añadido deja su
        # FetchWorker ya terminado colgado en memoria hasta cerrar el panel.
        worker.finished.connect(
            lambda w=worker: self._probe_workers.remove(w) if w in self._probe_workers else None,
            Qt.QueuedConnection,
        )
        self._probe_workers.append(worker)
        worker.start()

    def _on_duration_probed(self, item: "_Item", info: "dict | None"):
        if info and info.get("duration_ms"):
            item.duration_ms = info["duration_ms"]
            if self._current_item() is item:
                self._refresh_marks_label()

    def _on_remove_selected(self):
        idx = self.file_list.currentRow()
        if idx < 0:
            return
        self._stop_preview()
        self.file_list.takeItem(idx)
        del self._items[idx]
        self._update_status_idle()

    def _on_move_up(self):
        idx = self.file_list.currentRow()
        if idx <= 0:
            return
        self._swap_items(idx, idx - 1)
        self.file_list.setCurrentRow(idx - 1)

    def _on_move_down(self):
        idx = self.file_list.currentRow()
        if idx < 0 or idx >= len(self._items) - 1:
            return
        self._swap_items(idx, idx + 1)
        self.file_list.setCurrentRow(idx + 1)

    def _swap_items(self, i: int, j: int):
        self._items[i], self._items[j] = self._items[j], self._items[i]
        item_i = self.file_list.item(i)
        item_j = self.file_list.item(j)
        texto_i, texto_j = item_i.text(), item_j.text()
        item_i.setText(texto_j)
        item_j.setText(texto_i)

    def _update_status_idle(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if len(self._items) >= 1:
            self.status_label.setText(f"{len(self._items)} archivo(s) en la lista.")
            set_visual_state(self.status_label, "default")
        else:
            self.status_label.setText(
                "Añade al menos dos MP3, márcales inicio/fin (opcional) y pulsa Unir."
            )
            set_visual_state(self.status_label, "empty")

    # ---------- vista previa ----------

    def _current_item(self) -> "_Item | None":
        idx = self.file_list.currentRow()
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def _on_selection_changed(self, _row: int):
        self._stop_preview()
        item = self._current_item()
        self.play_btn.setEnabled(item is not None)
        self._refresh_marks_label()

    def _stop_preview(self):
        self._poll_timer.stop()
        self._preview.stop()
        self.play_btn.setText("▶")
        self.position_label.setText("--:-- / --:--")

    def _on_play_pause(self):
        item = self._current_item()
        if item is None:
            return
        if self._preview.is_playing():
            self._preview.pause()
            self.play_btn.setText("▶")
            self._poll_timer.stop()
            return
        if self._preview.get_length_ms() == 0 or self._preview_loaded_path != item.path:
            self._preview.load(item.path)
            self._preview_loaded_path = item.path
        self._preview.play()
        self.play_btn.setText("⏸")
        self._poll_timer.start()

    def _on_poll_preview(self):
        item = self._current_item()
        if item is None:
            return
        pos = self._preview.get_time_ms()
        dur = self._preview.get_length_ms()
        if dur:
            item.duration_ms = dur
        self.position_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(item.duration_ms)}")

    def _on_preview_end(self):
        self.play_btn.setText("▶")
        self._poll_timer.stop()

    def _on_preview_error(self, mensaje: str):
        self._poll_timer.stop()
        self.play_btn.setText("▶")
        QMessageBox.warning(self, "Error de vista previa", mensaje)

    def _on_mark_start(self):
        item = self._current_item()
        if item is None:
            return
        item.start_ms = self._preview.get_time_ms()
        self._refresh_marks_label()

    def _on_mark_end(self):
        item = self._current_item()
        if item is None:
            return
        item.end_ms = self._preview.get_time_ms()
        self._refresh_marks_label()

    def _on_reset_trim(self):
        item = self._current_item()
        if item is None:
            return
        item.start_ms = None
        item.end_ms = None
        self._refresh_marks_label()

    def _refresh_marks_label(self):
        item = self._current_item()
        if item is None:
            self.marks_label.setText("Selecciona un archivo de la lista para recortarlo.")
            return
        duracion = f"   ·   Duración: {_fmt_ms(item.duration_ms)}" if item.duration_ms else ""
        self.marks_label.setText(
            f"Inicio: {_fmt_ms(item.start_ms)}   ·   Fin: {_fmt_ms(item.end_ms)}"
            f"{duracion}   (sin marcar = desde/hasta el propio límite del archivo)"
        )

    # ---------- unión ----------

    def _on_join(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._items:
            QMessageBox.information(self, "Nada que unir", "Añade al menos un MP3.")
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar MP3 unido como…", "union.mp3", "Audio MP3 (*.mp3)"
        )
        if not output_path:
            return
        if not output_path.lower().endswith(".mp3"):
            output_path += ".mp3"

        self._stop_preview()
        segments = [
            Segment(path=it.path, start_ms=it.start_ms, end_ms=it.end_ms)
            for it in self._items
        ]
        fade = self.fade_spin.value()
        total_ms = self._expected_total_ms(fade)

        self._set_busy(True, progreso_conocido=total_ms > 0)
        if total_ms > 0:
            self.status_label.setText(f"Uniendo… duración estimada ~{_fmt_ms(total_ms)}")
        else:
            self.status_label.setText("Uniendo…")
        set_visual_state(self.status_label, "default")

        self._worker = AudioEditWorker(segments, fade, output_path, expected_total_ms=total_ms, parent=self)
        self._worker.progress.connect(self._on_join_progress)
        self._worker.finished_ok.connect(self._on_join_done)
        self._worker.failed.connect(self._on_join_failed)
        self._worker.start()

    def _expected_total_ms(self, fade_seconds: float) -> int:
        """Duración total esperada del resultado, para poder traducir el
        progreso de ffmpeg (out_time_ms) a un %. Se apoya en item.duration_ms
        (ver _probe_duration) cuando "Fin" no está marcado -- si algún
        archivo aún no tiene duración conocida (probe en curso o falló),
        devuelve 0 y la UI cae a una barra indeterminada en vez de mostrar
        un % incorrecto."""
        total = 0
        for it in self._items:
            fin = it.end_ms if it.end_ms is not None else it.duration_ms
            if fin is None:
                return 0
            total += max(0, fin - (it.start_ms or 0))
        if len(self._items) > 1:
            total -= int(fade_seconds * 1000) * (len(self._items) - 1)
        return max(0, total)

    def _set_busy(self, ocupado: bool, progreso_conocido: bool = False):
        self.join_btn.setEnabled(not ocupado)
        self.join_btn.setText("Uniendo…" if ocupado else "Unir")
        self.cancel_btn.setVisible(ocupado)
        self.cancel_btn.setEnabled(ocupado)
        self.progress_bar.setVisible(ocupado)
        if ocupado:
            self.progress_bar.setRange(0, 100 if progreso_conocido else 0)
            self.progress_bar.setTextVisible(progreso_conocido)
            self.progress_bar.setValue(0)

    def _on_join_progress(self, frac: float):
        self.progress_bar.setValue(int(frac * 100))

    def _on_cancel_join(self):
        if self._worker is None or not self._worker.isRunning():
            return
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelando…")
        self._worker.cancel()

    def _on_join_done(self, output_path: str):
        self._set_busy(False)
        self.status_label.setText(f"Completado → {output_path}")
        set_visual_state(self.status_label, "default")
        resp = QMessageBox.question(
            self, "MP3 unido", f"Se guardó en:\n{output_path}\n\n¿Abrir la carpeta?",
        )
        if resp == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(output_path)))

    def _on_join_failed(self, mensaje: str):
        self._set_busy(False)
        if mensaje == "__cancelled__":
            self.status_label.setText("Unión cancelada.")
            set_visual_state(self.status_label, "default")
            return
        self.status_label.setText("Error al unir los MP3.")
        set_visual_state(self.status_label, "error")
        QMessageBox.warning(self, "Error al unir", mensaje)

    # ---------- cierre ordenado ----------

    def shutdown(self, on_wait=None):
        self._poll_timer.stop()
        self._preview.release()
        shutdown_workers(self._probe_workers)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)

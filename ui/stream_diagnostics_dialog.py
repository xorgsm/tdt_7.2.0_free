"""Diálogo no bloqueante para comprobar el catálogo de streams."""
import csv
import threading

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core import channels as tv_store
from core import radio as radio_store
from core.stream_health import diagnose_catalog, safe_csv_cell, summarize_results
from core.stream_health_store import derive_health_status, record_results, summarize_health
from ui import palette
from ui.visual import set_surface


class StreamDiagnosticsWorker(QThread):
    result_ready = Signal(dict)
    progress = Signal(int, int)
    completed = Signal(bool)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = entries
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        def report(result, completed, total):
            self.result_ready.emit(result)
            self.progress.emit(completed, total)

        diagnose_catalog(self.entries, report, self._cancel_event)
        self.completed.emit(self._cancel_event.is_set())


class StreamDiagnosticsDialog(QDialog):
    def __init__(self, tv_channels, radio_stations, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Diagnóstico de canales y emisoras")
        self.resize(900, 560)
        self._close_when_done = False
        self._results = []
        self.catalog_changed = False
        self._custom_tv_keys = {(channel.name, channel.url) for channel in tv_store.load_custom_channels()}
        self._custom_radio_keys = {
            (station.name, station.url) for station in radio_store.load_custom_stations()
        }

        entries = [
            {"kind": "tv", "name": channel.name, "url": channel.url}
            for channel in tv_channels
            if channel.url
        ] + [
            {"kind": "radio", "name": station.name, "url": station.url}
            for station in radio_stations
            if station.url
        ]

        root = QVBoxLayout(self)
        title = QLabel("Comprobando disponibilidad, redirecciones y tiempo de respuesta")
        title.setWordWrap(True)
        root.addWidget(title)

        summary_row = QHBoxLayout()
        self.summary = QLabel(f"0 de {len(entries)} comprobados")
        self.summary.setStyleSheet(f"color: {palette.TEXT_MUTED};")
        summary_row.addWidget(self.summary)
        summary_row.addStretch(1)
        self.filter_btn = QPushButton("Mostrar solo problemas")
        self.filter_btn.setCheckable(True)
        self.filter_btn.toggled.connect(self._apply_filter)
        summary_row.addWidget(self.filter_btn)
        root.addLayout(summary_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(1, len(entries)))
        root.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Estado", "Tipo", "Nombre", "HTTP", "Respuesta", "Contenido / detalle"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 65)
        self.table.setColumnWidth(2, 230)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.export_btn = QPushButton("Exportar informe CSV…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        footer.addWidget(self.export_btn)
        self.remove_failed_btn = QPushButton("Ocultar/eliminar fallidos")
        self.remove_failed_btn.setToolTip(
            "Oculta los elementos fallidos del catálogo público y elimina los personalizados."
        )
        self.remove_failed_btn.setEnabled(False)
        self.remove_failed_btn.clicked.connect(self._remove_failed)
        footer.addWidget(self.remove_failed_btn)
        footer.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self._cancel_or_close)
        footer.addWidget(self.buttons)
        root.addLayout(footer)

        self.worker = StreamDiagnosticsWorker(entries, self)
        self.worker.result_ready.connect(self._add_result)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_completed)
        if entries:
            self.worker.start()
        else:
            self.summary.setText("No hay canales ni emisoras cargados.")

    def _add_result(self, result):
        self._results.append(result)
        self.export_btn.setEnabled(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        health_status = derive_health_status(result)
        labels = {
            "stable": "Estable",
            "slow": "Lento",
            "restricted": "Restringido",
            "down": "Caído",
        }
        colors = {
            "stable": Qt.green,
            "slow": Qt.yellow,
            "restricted": Qt.red,
            "down": Qt.red,
        }
        detail = result.get("content_type") or result.get("error") or "Sin tipo de contenido"
        values = [labels[health_status], "TV" if result.get("kind") == "tv" else "Radio",
                  result.get("name", ""), str(result.get("http_status") or "—"),
                  f'{result.get("latency_ms", 0)} ms', detail]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, health_status)
            if column == 0:
                item.setForeground(colors[health_status])
            self.table.setItem(row, column, item)
        self._apply_filter(self.filter_btn.isChecked())

    def _on_progress(self, completed, total):
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(completed)
        report = summarize_results(self._results)
        health = summarize_health(self._results)
        self.summary.setText(
            f"{completed} de {total} comprobados · {report['problems']} problemas "
            f"(TV {report['tv_problems']} · Radio {report['radio_problems']}) · "
            f"{health['stable']} estables · {health['slow']} lentos"
        )

    def _apply_filter(self, only_problems):
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(
                row, bool(only_problems and self.table.item(row, 0).data(Qt.UserRole) == "stable")
            )

    def _cancel_or_close(self):
        if self.worker.isRunning():
            self._close_when_done = True
            self.worker.cancel()
            self.summary.setText("Cancelando comprobaciones en curso…")
            self.buttons.setEnabled(False)
        else:
            self.accept()

    def _on_completed(self, cancelled):
        self.buttons.setEnabled(True)
        if cancelled and self._close_when_done:
            self.accept()
        elif not cancelled:
            try:
                record_results(self._results)
            except OSError:
                # No se pierde el informe actual si el perfil no se puede escribir.
                pass
            self.summary.setText(self.summary.text() + " · Diagnóstico terminado")
            self.table.setSortingEnabled(True)
            self.table.sortItems(0, Qt.AscendingOrder)
            self.remove_failed_btn.setEnabled(
                any(derive_health_status(result) != "stable" for result in self._results)
            )

    def _remove_failed(self):
        failed = [result for result in self._results if derive_health_status(result) != "stable"]
        if not failed:
            return
        confirmation = QMessageBox.question(
            self,
            "Quitar elementos fallidos",
            f"Se quitarán {len(failed)} elementos lentos, con error o acceso restringido.\n\n"
            "Los elementos públicos quedarán ocultos para que no reaparezcan al actualizar. "
            "Los personalizados se eliminarán de forma permanente.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        custom_tv = set()
        hidden_tv = set()
        custom_radio = set()
        hidden_radio = set()
        for result in failed:
            key = (result.get("name", ""), result.get("url", ""))
            if result.get("kind") == "tv":
                (custom_tv if key in self._custom_tv_keys else hidden_tv).add(key[0])
            else:
                (custom_radio if key in self._custom_radio_keys else hidden_radio).add(key[0])

        removed_tv = tv_store.remove_custom_channels(custom_tv)
        removed_radio = radio_store.remove_custom_stations(custom_radio)
        hidden_tv_count = tv_store.hide_channels(hidden_tv)
        hidden_radio_count = radio_store.hide_stations(hidden_radio)
        self.catalog_changed = bool(removed_tv or removed_radio or hidden_tv_count or hidden_radio_count)
        self.remove_failed_btn.setEnabled(False)
        self.summary.setText(
            f"Eliminados {removed_tv + removed_radio} personalizados · "
            f"ocultados {hidden_tv_count + hidden_radio_count} del catálogo público"
        )

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar diagnóstico", "diagnostico_streams.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as output:
                writer = csv.writer(output)
                writer.writerow([
                    "estado", "tipo", "nombre", "url_original", "url_final",
                    "http", "respuesta_ms", "tipo_contenido", "detalle",
                ])
                for result in self._results:
                    writer.writerow([safe_csv_cell(value) for value in (
                        result.get("status"), result.get("kind"), result.get("name"),
                        result.get("url"), result.get("final_url"), result.get("http_status"),
                        result.get("latency_ms"), result.get("content_type"), result.get("error"),
                    )])
            self.summary.setText(f"Informe guardado en {path}")
        except OSError as exc:
            self.summary.setText(f"No se pudo guardar el informe: {exc}")

    def closeEvent(self, event):
        if self.worker.isRunning():
            self._cancel_or_close()
            event.ignore()
            return
        super().closeEvent(event)

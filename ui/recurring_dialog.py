"""
Diálogo de gestión de grabaciones recurrentes ("todos los días X a las
Y en el canal Z"), independientes de la guía EPG -- ver
core/recurring_recordings.py para el porqué y cómo se integran con las
grabaciones programadas ya existentes.

Coder By X@R
"""
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QTimeEdit, QVBoxLayout,
)

from core import recurring_recordings as recurring
from ui import palette
from ui.visual import set_surface

DIAS_CORTO = ("L", "M", "X", "J", "V", "S", "D")


class _NuevaReglaDialog(QDialog):
    """Formulario para dar de alta una regla nueva."""

    def __init__(self, parent, canales):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Nueva grabación recurrente")
        self.setMinimumWidth(380)
        self.result_rule = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.canal_combo = QComboBox()
        for ch in canales:
            self.canal_combo.addItem(ch.name, (ch.name, ch.url))
        form.addRow("Canal:", self.canal_combo)

        dias_row = QHBoxLayout()
        dias_row.setSpacing(6)
        self._dia_checks = []
        for letra in DIAS_CORTO:
            cb = QCheckBox(letra)
            dias_row.addWidget(cb)
            self._dia_checks.append(cb)
        form.addRow("Días:", dias_row)

        self.hora_edit = QTimeEdit(QTime(20, 0))
        self.hora_edit.setDisplayFormat("HH:mm")
        form.addRow("Hora de inicio:", self.hora_edit)

        self.duracion_spin = QSpinBox()
        self.duracion_spin.setRange(1, recurring.MAX_DURATION_MINUTES)
        self.duracion_spin.setValue(60)
        self.duracion_spin.setSuffix(" min")
        form.addRow("Duración:", self.duracion_spin)

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Guardar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_accept(self):
        if self.canal_combo.count() == 0:
            QMessageBox.warning(self, "Sin canales", "No hay canales de TV cargados todavía.")
            return
        dias = [i for i, cb in enumerate(self._dia_checks) if cb.isChecked()]
        if not dias:
            QMessageBox.warning(self, "Faltan días", "Elige al menos un día de la semana.")
            return
        name, url = self.canal_combo.currentData()
        self.result_rule = {
            "channel_name": name, "channel_url": url, "days": dias,
            "start_time": self.hora_edit.time().toString("HH:mm"),
            "duration_minutes": self.duracion_spin.value(),
        }
        self.accept()


class RecurringRecordingsDialog(QDialog):
    """Lista las reglas existentes, con botones para añadir/eliminar."""

    def __init__(self, parent, canales):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Grabaciones recurrentes")
        self.setMinimumWidth(440)
        self._canales = canales

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        subtitle = QLabel(
            "Se graban automáticamente los días y a la hora que elijas, sin "
            "depender de que la guía de programación tenga datos para ese canal."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8.5pt;")
        root.addWidget(subtitle)

        self.list_widget = QListWidget()
        root.addWidget(self.list_widget, stretch=1)

        botones_row = QHBoxLayout()
        add_btn = QPushButton("+ Añadir…")
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_remove)
        botones_row.addWidget(add_btn)
        botones_row.addWidget(del_btn)
        botones_row.addStretch(1)
        root.addLayout(botones_row)

        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.accept)
        close_buttons.accepted.connect(self.accept)
        root.addWidget(close_buttons)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        for rule in recurring.load_rules():
            dias_txt = "".join(DIAS_CORTO[d] for d in sorted(rule.days))
            texto = f"{rule.channel_name} — {dias_txt} {rule.start_time} ({rule.duration_minutes} min)"
            item = QListWidgetItem(texto)
            item.setData(Qt.UserRole, rule.id)
            self.list_widget.addItem(item)

    def _on_add(self):
        if not self._canales:
            QMessageBox.information(self, "Sin canales", "Espera a que carguen los canales de TV.")
            return
        dialog = _NuevaReglaDialog(self, self._canales)
        if dialog.exec() == QDialog.Accepted and dialog.result_rule:
            recurring.add_rule(**dialog.result_rule)
            self._reload()

    def _on_remove(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        recurring.remove_rule(item.data(Qt.UserRole))
        self._reload()

"""
Parrilla de programación (guía de TV tipo "qué echan ahora"), a partir de
los datos EPG ya descargados por core/epg.py.

Filas = canales de TV con datos de EPG. Columnas = franjas de 30 minutos.
Cada programa ocupa tantas columnas como le correspondan por duración
(fusión de celdas), con el que está en emisión ahora mismo resaltado en
dorado. Un clic en cualquier programa sintoniza ese canal en directo.

Coder By X@R
"""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from core.epg import channel_key, parse_xmltv_time
from core import epg_reminders
from core import recording_schedule
from ui import palette
from ui.visual import set_surface

SLOT_MINUTES = 30
VISIBLE_SLOTS = 8  # 4 horas visibles a la vez
SLOT_WIDTH = 132


class EpgDialog(QDialog):
    channel_chosen = Signal(str)  # tvg_id del canal elegido

    def __init__(self, channels, epg_guide: dict, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setObjectName("epgDialog")
        self.setWindowTitle("Guía de programación")
        self.resize(920, 560)

        self.epg_guide = epg_guide or {}
        # Solo los canales que de verdad tienen datos de programación: una
        # fila entera de "sin datos" por cada canal sin EPG no aporta nada,
        # solo ensancha la parrilla sin necesidad.
        self.channels = [
            c for c in channels if channel_key(getattr(c, "tvg_id", "")) in self.epg_guide
        ]

        now = datetime.now()
        minute = 0 if now.minute < 30 else 30
        self.window_start = now.replace(minute=minute, second=0, microsecond=0)

        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        if not self.channels:
            msg = QLabel(
                "No hay datos de programación disponibles todavía.\n"
                "Configura una URL de EPG (XMLTV) en Configuración, o espera "
                "a que termine de descargarse."
            )
            msg.setAlignment(Qt.AlignCenter)
            msg.setStyleSheet(f"color: {palette.TEXT_MUTED}; padding: 40px;")
            layout.addWidget(msg, stretch=1)
            return

        nav_row = QHBoxLayout()
        prev_btn = QPushButton("\u2190")
        prev_btn.setObjectName("ctrlButton")
        prev_btn.setToolTip("2 horas antes")
        prev_btn.clicked.connect(lambda: self._shift(-2))
        self.range_label = QLabel()
        self.range_label.setAlignment(Qt.AlignCenter)
        self.range_label.setStyleSheet("font-weight: 600; font-size: 11pt;")
        now_btn = QPushButton("Ahora")
        now_btn.setObjectName("primaryButton")
        now_btn.clicked.connect(self._reset_to_now)
        next_btn = QPushButton("\u2192")
        next_btn.setObjectName("ctrlButton")
        next_btn.setToolTip("2 horas después")
        next_btn.clicked.connect(lambda: self._shift(2))
        nav_row.addWidget(prev_btn)
        nav_row.addWidget(self.range_label, stretch=1)
        nav_row.addWidget(now_btn)
        nav_row.addWidget(next_btn)
        layout.addLayout(nav_row)

        self.table = QTableWidget()
        self.table.setColumnCount(VISIBLE_SLOTS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: {palette.EPG_CELL_BG};
                color: {palette.EPG_CELL_TEXT};
                border: 1px solid {palette.BORDER};
                selection-background-color: {palette.EPG_NOW_BG};
            }}
            QHeaderView::section {{
                background: {palette.BG_PANEL_ALT};
                color: {palette.TEXT_PRIMARY};
                border: none;
                border-right: 1px solid {palette.BORDER};
                border-bottom: 1px solid {palette.BORDER};
                padding: 8px 10px;
            }}
        """)
        vertical_header = self.table.verticalHeader()
        vertical_header.setDefaultSectionSize(52)
        vertical_header.setMinimumWidth(250)
        vertical_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        for col in range(VISIBLE_SLOTS):
            self.table.setColumnWidth(col, SLOT_WIDTH)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table, stretch=1)

    def _shift(self, hours: int):
        self.window_start += timedelta(hours=hours)
        self._populate()

    def _reset_to_now(self):
        now = datetime.now()
        minute = 0 if now.minute < 30 else 30
        self.window_start = now.replace(minute=minute, second=0, microsecond=0)
        self._populate()

    def _populate(self):
        if not self.channels:
            return
        window_end = self.window_start + timedelta(minutes=SLOT_MINUTES * VISIBLE_SLOTS)
        now = datetime.now()
        # Se recarga en cada _populate() (no solo al abrir el diálogo) para
        # reflejar sin retraso lo que el QTimer de MainWindow vaya
        # cambiando en segundo plano (p. ej. "recording" -> se quita al
        # terminar) mientras el usuario tiene la parrilla abierta.
        self._grabaciones_programadas = recording_schedule.load_scheduled()

        headers = []
        t = self.window_start
        for _ in range(VISIBLE_SLOTS):
            headers.append(t.strftime("%H:%M"))
            t += timedelta(minutes=SLOT_MINUTES)
        self.table.setHorizontalHeaderLabels(headers)
        self.range_label.setText(
            f"{self.window_start.strftime('%d/%m %H:%M')} — {window_end.strftime('%H:%M')}"
        )

        self.table.setRowCount(len(self.channels))
        self.table.setVerticalHeaderLabels([c.name for c in self.channels])

        for row, ch in enumerate(self.channels):
            # Limpiar fusiones de celdas de la ventana de tiempo anterior
            # antes de repintar, o los "span" viejos dejan basura visual.
            for col in range(VISIBLE_SLOTS):
                self.table.setSpan(row, col, 1, 1)
                empty_item = QTableWidgetItem("")
                empty_item.setBackground(QColor(palette.EPG_CELL_BG))
                empty_item.setForeground(QColor(palette.EPG_CELL_TEXT))
                self.table.setItem(row, col, empty_item)

            programmes = sorted(
                self.epg_guide.get(channel_key(ch.tvg_id), []), key=lambda p: p.start
            )
            for prog in programmes:
                start = parse_xmltv_time(prog.start)
                stop = parse_xmltv_time(prog.stop)
                if not start or not stop or stop <= self.window_start or start >= window_end:
                    continue

                clip_start = max(start, self.window_start)
                clip_stop = min(stop, window_end)
                start_offset = (clip_start - self.window_start).total_seconds() / (SLOT_MINUTES * 60)
                end_offset = (clip_stop - self.window_start).total_seconds() / (SLOT_MINUTES * 60)
                col_start = int(start_offset)  # floor: franja donde empieza
                col_end = -int(-end_offset // 1)  # ceil: franja donde termina
                # OJO: redondear hacia arriba solo la DURACIÓN (como se hacía
                # antes) infravalora el ancho cuando el programa no empieza
                # alineado con una franja de 30 min — p. ej. 14:45–15:15 dura
                # exactamente un slot, pero pisa DOS franjas (14:30-15:00 y
                # 15:00-15:30) y debe ocupar 2 columnas, no 1. Calculando la
                # columna de fin por separado y restando, sale bien siempre.
                col_span = max(1, col_end - col_start)
                col_span = min(col_span, VISIBLE_SLOTS - col_start)
                if col_span <= 0:
                    continue

                item = QTableWidgetItem(prog.title or "(sin título)")
                item.setData(Qt.UserRole, ch.tvg_id)
                item.setData(Qt.UserRole + 1, prog.title or "")
                item.setData(Qt.UserRole + 2, prog.start)
                item.setData(Qt.UserRole + 3, ch.name)
                item.setData(Qt.UserRole + 4, prog.stop)
                item.setData(Qt.UserRole + 5, ch.url)
                tiene_aviso = epg_reminders.has_reminder(ch.tvg_id, prog.title or "", prog.start)
                grabacion = next(
                    (r for r in self._grabaciones_programadas
                     if r.tvg_id == ch.tvg_id and r.title == (prog.title or "") and r.start == prog.start),
                    None,
                )
                etiqueta = ""
                if grabacion is not None:
                    etiqueta = "[REC] " if grabacion.status != "error" else "[REC ✗] "
                elif tiene_aviso:
                    etiqueta = "[Aviso] "
                texto_item = etiqueta + (prog.title or "(sin título)")
                item.setText(texto_item)
                tooltip_extra = ""
                if grabacion is not None and grabacion.status == "error":
                    tooltip_extra = "\n\nGrabación programada FALLIDA — clic derecho para quitarla"
                elif grabacion is not None:
                    tooltip_extra = "\n\nGrabación programada — clic derecho para cancelarla"
                elif tiene_aviso:
                    tooltip_extra = "\n\nAviso puesto — clic derecho para quitarlo"
                item.setToolTip(
                    f"{prog.title}\n{start.strftime('%H:%M')}–{stop.strftime('%H:%M')}"
                    + tooltip_extra
                    + (f"\n\n{prog.description}" if prog.description else "")
                )
                is_now = start <= now <= stop
                if is_now:
                    item.setBackground(QColor(palette.EPG_NOW_BG))
                    item.setForeground(QColor(palette.ACCENT_LIGHTER))
                else:
                    item.setBackground(QColor(palette.EPG_CELL_BG))
                    item.setForeground(QColor(palette.EPG_CELL_TEXT))
                if grabacion is not None:
                    item.setForeground(QColor(palette.DANGER))
                elif tiene_aviso:
                    item.setForeground(QColor(palette.ACCENT_SLEEP))
                self.table.setItem(row, col_start, item)
                if col_span > 1:
                    self.table.setSpan(row, col_start, 1, col_span)

    def _on_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        tvg_id = item.data(Qt.UserRole)
        title = item.data(Qt.UserRole + 1)
        start = item.data(Qt.UserRole + 2)
        channel_name = item.data(Qt.UserRole + 3)
        stop = item.data(Qt.UserRole + 4)
        channel_url = item.data(Qt.UserRole + 5)
        if not tvg_id or not start:
            return

        menu = QMenu(self)
        tiene_aviso = epg_reminders.has_reminder(tvg_id, title or "", start)
        accion_aviso = menu.addAction("Quitar aviso" if tiene_aviso else "Avisarme cuando empiece")

        tiene_grabacion = recording_schedule.has_scheduled(tvg_id, title or "", start)
        if tiene_grabacion:
            accion_grabacion = menu.addAction("Cancelar grabación programada")
        else:
            accion_grabacion = menu.addAction("Grabar automáticamente")
            # Sin URL o sin hora de fin no hay nada que arrancar/parar --
            # se deshabilita la opción en vez de dejar programar algo que
            # luego nunca podría grabarse de verdad.
            accion_grabacion.setEnabled(bool(channel_url and stop))

        elegido = menu.exec(self.table.viewport().mapToGlobal(pos))
        if elegido is None:
            return

        if elegido is accion_aviso:
            if tiene_aviso:
                epg_reminders.remove_reminder(tvg_id, title or "", start)
            else:
                epg_reminders.add_reminder(epg_reminders.Reminder(
                    tvg_id=tvg_id, channel_name=channel_name or "", title=title or "", start=start,
                ))
        elif elegido is accion_grabacion:
            if tiene_grabacion:
                recording_schedule.remove_scheduled(tvg_id, title or "", start)
            else:
                recording_schedule.add_scheduled(recording_schedule.ScheduledRecording(
                    tvg_id=tvg_id, channel_name=channel_name or "", channel_url=channel_url or "",
                    title=title or "", start=start, stop=stop or "",
                ))
        self._populate()  # repinta para reflejar el cambio (texto y color)

    def _on_cell_clicked(self, row: int, _col: int):
        item = self.table.item(row, _col)
        tvg_id = item.data(Qt.UserRole) if item else None
        if not tvg_id and 0 <= row < len(self.channels):
            tvg_id = self.channels[row].tvg_id
        if tvg_id:
            self.channel_chosen.emit(tvg_id)
            self.accept()

"""
Diálogos de la aplicación: preferencias, añadir canal/emisora manual
e importar listas M3U completas (por URL o archivo local).
"""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core import config as cfg
from core import countries
from core.recording_library import list_recordings
from ui import palette
from ui.style import ACCENT_PRESETS, DEFAULT_ACCENT
from ui.visual import set_surface


def _panel(section_label: str) -> tuple[QFrame, QFormLayout]:
    """
    Panel con textura (mismo lenguaje visual que la barra de reproducción)
    y una etiqueta de sección en mayúsculas arriba, con un QFormLayout
    dentro listo para añadir filas. Evita repetir este bloque en cada
    sección de cada diálogo.
    """
    frame = QFrame()
    frame.setObjectName("dialogPanel")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(16, 14, 16, 14)
    outer.setSpacing(8)

    label = QLabel(section_label.upper())
    label.setObjectName("dialogSectionLabel")
    outer.addWidget(label)

    form = QFormLayout()
    form.setSpacing(10)
    form.setContentsMargins(0, 4, 0, 0)
    outer.addLayout(form)
    return frame, form


def _header(title: str, subtitle: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("dialogTitle")
    box.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)
        box.addWidget(subtitle_label)
    return box


class RecordingsLibraryDialog(QDialog):
    """Biblioteca local de grabaciones sin modificar el catálogo de canales."""

    def __init__(self, recordings_dir: str, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Biblioteca de grabaciones")
        self.setMinimumSize(720, 440)
        self._directory = Path(recordings_dir)

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Biblioteca de grabaciones",
            "Tus grabaciones de TV y radio. Puedes abrirlas, mostrar su carpeta o eliminar las que ya no necesites.",
        ))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tipo", "Tamaño", "Fecha"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._open_selected)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 90)
        root.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self._reload)
        actions.addWidget(refresh)
        open_folder = QPushButton("Abrir carpeta")
        open_folder.clicked.connect(self._open_folder)
        actions.addWidget(open_folder)
        actions.addStretch(1)
        self.open_btn = QPushButton("Abrir")
        self.open_btn.clicked.connect(self._open_selected)
        actions.addWidget(self.open_btn)
        self.delete_btn = QPushButton("Eliminar seleccionadas")
        self.delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(self.delete_btn)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)
        self._reload()

    def _reload(self):
        self.table.setRowCount(0)
        for recording in list_recordings(self._directory):
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(recording.path.name)
            name.setData(Qt.UserRole, str(recording.path))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem("Radio" if recording.path.suffix.casefold() == ".mka" else "TV"))
            self.table.setItem(row, 2, QTableWidgetItem(self._format_size(recording.size)))
            date = datetime.fromtimestamp(recording.modified).strftime("%d/%m/%Y %H:%M")
            self.table.setItem(row, 3, QTableWidgetItem(date))
        is_empty = self.table.rowCount() == 0
        self.open_btn.setEnabled(not is_empty)
        self.delete_btn.setEnabled(not is_empty)

    def _selected_paths(self) -> list[Path]:
        paths = []
        for index in self.table.selectionModel().selectedRows():
            value = self.table.item(index.row(), 0).data(Qt.UserRole)
            if value:
                paths.append(Path(value))
        return paths

    def _open_selected(self):
        paths = self._selected_paths()
        if paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0])))

    def _open_folder(self):
        self._directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._directory)))

    def _delete_selected(self):
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "Selecciona grabaciones", "Selecciona una o más grabaciones para eliminarlas.")
            return
        if QMessageBox.question(
            self, "Eliminar grabaciones",
            f"Vas a eliminar {len(paths)} grabación(es) de forma permanente.\n\n¿Continuar?",
        ) != QMessageBox.Yes:
            return
        errors = 0
        for path in paths:
            try:
                path.unlink()
                log = path.with_suffix(".log")
                if log.exists():
                    log.unlink()
            except OSError:
                errors += 1
        self._reload()
        if errors:
            QMessageBox.warning(self, "No se pudieron eliminar todas", f"No se pudieron eliminar {errors} grabación(es).")

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(480)
        self.settings = dict(settings)

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Configuración",
            "Fuentes de contenido, grabación y aspecto de la aplicación.",
        ))

        # ---- Canales ----
        panel_canales, form_canales = _panel("Canales")
        self.tv_country_combo = QComboBox()
        self._fill_country_combo(self.tv_country_combo, self.settings.get("tv_country_code", "ES"))
        form_canales.addRow("País de TV:", self.tv_country_combo)

        self.tv_url_input = QLineEdit(self.settings.get("tv_playlist_url", ""))
        self.tv_url_input.setPlaceholderText("(opcional) URL M3U propia — anula el país de arriba")
        form_canales.addRow("Lista TV personalizada:", self.tv_url_input)

        self.radio_country_combo = QComboBox()
        self._fill_country_combo(self.radio_country_combo, self.settings.get("radio_country_code", "ES"))
        form_canales.addRow("País de radio:", self.radio_country_combo)
        root.addWidget(panel_canales)

        # ---- Guía y grabaciones ----
        panel_grab, form_grab = _panel("Guía y grabaciones")
        self.epg_input = QLineEdit(self.settings.get("epg_url", ""))
        self.epg_input.setPlaceholderText("URL de guía XMLTV (opcional)")
        form_grab.addRow("EPG (XMLTV):", self.epg_input)

        rec_row = QHBoxLayout()
        self.rec_dir_input = QLineEdit(self.settings.get("recordings_dir", ""))
        browse_btn = QPushButton("Examinar…")
        browse_btn.clicked.connect(self._browse_dir)
        rec_row.addWidget(self.rec_dir_input)
        rec_row.addWidget(browse_btn)
        form_grab.addRow("Carpeta de grabaciones:", rec_row)
        root.addWidget(panel_grab)

        # ---- Apariencia ----
        panel_apariencia, form_apariencia = _panel("Apariencia")
        accent_row = QHBoxLayout()
        accent_row.setSpacing(8)
        self._accent_group = QButtonGroup(self)
        self._accent_buttons = {}
        accent_actual = (self.settings.get("accent_color") or DEFAULT_ACCENT).lower()
        # ¿El acento guardado es uno de los 6 predefinidos, o uno elegido a
        # mano la última vez? Si es "a mano", el botón de color libre debe
        # arrancar ya marcado y mostrando ese mismo tono, no en blanco.
        es_personalizado = accent_actual not in {c.lower() for c in ACCENT_PRESETS.values()}
        self._custom_color = accent_actual if es_personalizado else None
        self._custom_selected = es_personalizado

        for nombre, color in ACCENT_PRESETS.items():
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setToolTip(nombre)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; border-radius: 14px; "
                f"border: 2px solid transparent; }}"
                f"QPushButton:checked {{ border: 2px solid white; }}"
            )
            if not es_personalizado and color.lower() == accent_actual:
                btn.setChecked(True)
            btn.clicked.connect(self._on_preset_accent_clicked)
            self._accent_group.addButton(btn)
            self._accent_buttons[btn] = color
            accent_row.addWidget(btn)

        # Botón de color libre: no forma parte de _accent_group (los
        # predefinidos son mutuamente excluyentes entre sí vía
        # QButtonGroup, pero este necesita su propio estado -- "elegido a
        # mano" o no -- que no encaja con ser "un botón más del grupo").
        self._custom_btn = QPushButton()
        self._custom_btn.setFixedSize(28, 28)
        self._custom_btn.setToolTip("Color personalizado…")
        self._custom_btn.setCursor(Qt.PointingHandCursor)
        self._custom_btn.clicked.connect(self._on_pick_custom_color)
        self._refresh_custom_btn_style()
        accent_row.addWidget(self._custom_btn)

        accent_row.addStretch(1)
        form_apariencia.addRow("Color de acento:", accent_row)
        root.addWidget(panel_apariencia)

        # ---- Perfil ----
        panel_perfil, form_perfil = _panel("Perfil")
        perfil_row = QHBoxLayout()
        self.perfil_combo = QComboBox()
        self._reload_perfil_combo(self.settings.get("active_profile", "Default"))
        nuevo_perfil_btn = QPushButton("+ Nuevo perfil…")
        nuevo_perfil_btn.clicked.connect(self._on_nuevo_perfil)
        perfil_row.addWidget(self.perfil_combo, stretch=1)
        perfil_row.addWidget(nuevo_perfil_btn)
        form_perfil.addRow("Perfil activo:", perfil_row)
        perfil_aviso = QLabel(
            "Cada perfil tiene sus propios favoritos, historial, canales/emisoras "
            "añadidos a mano y grabaciones programadas. Cambiar de perfil pide "
            "reiniciar la aplicación para aplicarse del todo."
        )
        perfil_aviso.setWordWrap(True)
        perfil_aviso.setObjectName("dialogSubtitle")
        form_perfil.addRow(perfil_aviso)
        root.addWidget(panel_perfil)

        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("Guardar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _fill_country_combo(combo: QComboBox, selected_code: str):
        for code, name in countries.COUNTRIES:
            combo.addItem(name, code)
        idx = combo.findData((selected_code or "ES").upper())
        combo.setCurrentIndex(idx if idx >= 0 else combo.findData("ES"))

    def _browse_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Selecciona carpeta de grabaciones")
        if directory:
            self.rec_dir_input.setText(directory)

    # ---------- Color de acento ----------

    def _on_preset_accent_clicked(self):
        # Elegir un predefinido desmarca el color libre -- los dos son
        # alternativas, no se combinan.
        self._custom_selected = False
        self._refresh_custom_btn_style()

    def _on_pick_custom_color(self):
        inicial = QColor(self._custom_color or self.settings.get("accent_color") or DEFAULT_ACCENT)
        color = QColorDialog.getColor(inicial, self, "Elige un color de acento")
        if not color.isValid():
            return  # el usuario canceló el diálogo: no se toca nada
        self._custom_color = color.name()
        self._custom_selected = True
        # Elegir un color libre desmarca cualquier predefinido -- mismo
        # criterio que al revés en _on_preset_accent_clicked().
        checked = self._accent_group.checkedButton()
        if checked is not None:
            self._accent_group.setExclusive(False)
            checked.setChecked(False)
            self._accent_group.setExclusive(True)
        self._refresh_custom_btn_style()

    def _refresh_custom_btn_style(self):
        """
        Sin color elegido todavía: círculo neutro con un "+". Con uno
        elegido: círculo relleno de ese color, marcado con borde blanco
        solo si es la opción activa ahora mismo (el usuario puede haber
        vuelto a un predefinido después de probar uno personalizado, sin
        perder por eso el último color libre que había elegido).
        """
        if self._custom_color:
            fondo, texto = self._custom_color, ""
        else:
            fondo, texto = palette.BG_PANEL_ALT, "+"
        borde = "2px solid white" if self._custom_selected else "2px solid transparent"
        self._custom_btn.setText(texto)
        self._custom_btn.setStyleSheet(
            f"QPushButton {{ background-color: {fondo}; border-radius: 14px; "
            f"border: {borde}; color: white; font-weight: 700; }}"
        )

    def _reload_perfil_combo(self, seleccionar: str):
        self.perfil_combo.blockSignals(True)
        self.perfil_combo.clear()
        for nombre in cfg.list_profiles():
            self.perfil_combo.addItem(nombre, nombre)
        idx = self.perfil_combo.findData(seleccionar)
        self.perfil_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.perfil_combo.blockSignals(False)

    def _on_nuevo_perfil(self):
        nombre, ok = QInputDialog.getText(self, "Nuevo perfil", "Nombre del perfil nuevo:")
        nombre = (nombre or "").strip()
        if not ok or not nombre:
            return
        if nombre in cfg.list_profiles():
            QMessageBox.information(self, "Nuevo perfil", "Ya existe un perfil con ese nombre.")
            return
        try:
            cfg.create_profile(nombre)
        except ValueError:
            QMessageBox.warning(
                self, "Nuevo perfil",
                "Ese nombre no es válido (no puede contener \\ / : * ? \" < > | ni ser \".\" o \"..\").",
            )
            return
        self._reload_perfil_combo(nombre)

    def get_settings(self) -> dict:
        self.settings["tv_country_code"] = self.tv_country_combo.currentData()
        self.settings["tv_playlist_url"] = self.tv_url_input.text().strip()
        self.settings["radio_country_code"] = self.radio_country_combo.currentData()
        self.settings["epg_url"] = self.epg_input.text().strip()
        self.settings["recordings_dir"] = self.rec_dir_input.text().strip() or self.settings.get("recordings_dir")
        if self._custom_selected and self._custom_color:
            self.settings["accent_color"] = self._custom_color
        else:
            boton_marcado = self._accent_group.checkedButton()
            if boton_marcado is not None:
                self.settings["accent_color"] = self._accent_buttons[boton_marcado]
        self.settings["active_profile"] = self.perfil_combo.currentData() or "Default"
        return self.settings


class AddEntryDialog(QDialog):
    """Añadir (o editar) un único canal de TV o emisora de radio a mano."""

    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        set_surface(self, "dialog")
        editing = initial is not None
        self.editing = editing
        self.original_name = initial.get("name") if editing else None
        self.setWindowTitle("Editar canal o emisora" if editing else "Añadir canal o emisora")
        self.setMinimumWidth(460)
        self.result_data = None

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Editar canal o emisora" if editing else "Añadir canal o emisora",
            "Se guarda en tu lista personalizada, junto a los canales que ya tienes.",
        ))

        panel, form = _panel("Datos")

        self.type_combo = QComboBox()
        self.type_combo.addItem("Canal de TV", "tv")
        self.type_combo.addItem("Emisora de radio", "radio")
        if editing:
            idx = self.type_combo.findData(initial.get("type", "tv"))
            self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.type_combo.setEnabled(False)
        form.addRow("Tipo:", self.type_combo)

        self.name_input = QLineEdit(initial.get("name", "") if editing else "")
        self.name_input.setPlaceholderText("Nombre a mostrar")
        form.addRow("Nombre:", self.name_input)

        self.url_input = QLineEdit(initial.get("url", "") if editing else "")
        self.url_input.setPlaceholderText("https://.../stream.m3u8")
        form.addRow("URL del stream:", self.url_input)

        self.logo_input = QLineEdit(initial.get("logo", "") if editing else "")
        self.logo_input.setPlaceholderText("(opcional) URL de la imagen del logo")
        form.addRow("Logo:", self.logo_input)

        self.group_input = QLineEdit(initial.get("group", "") if editing else "")
        self.group_input.setPlaceholderText("(opcional) ej. Generalista, Deportes…")
        form.addRow("Categoría:", self.group_input)

        root.addWidget(panel)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("Guardar cambios" if editing else "Añadir")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_accept(self):
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "Faltan datos", "El nombre y la URL del stream son obligatorios.")
            return
        self.result_data = {
            "type": self.type_combo.currentData(),
            "name": name,
            "url": url,
            "logo": self.logo_input.text().strip(),
            "group": self.group_input.text().strip(),
        }
        self.accept()


class ImportPlaylistDialog(QDialog):
    """Importar una lista M3U/M3U8 completa desde una URL o un archivo local."""

    def __init__(self, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Importar lista M3U")
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Importar lista M3U",
            "Pega la URL de una lista M3U/M3U8 pública, o elige un archivo guardado "
            "en tu PC. Se añadirán todos los canales que contenga a tu lista "
            "personalizada, sin duplicar los que ya tienes.",
        ))

        panel, form = _panel("Origen")
        self.type_combo = QComboBox()
        self.type_combo.addItem("Canales de TV", "tv")
        self.type_combo.addItem("Emisoras de radio", "radio")
        form.addRow("Añadir como:", self.type_combo)

        source_row = QHBoxLayout()
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("URL http(s):// o ruta de un archivo .m3u/.m3u8")
        browse_btn = QPushButton("Examinar…")
        browse_btn.clicked.connect(self._browse_file)
        source_row.addWidget(self.source_input)
        source_row.addWidget(browse_btn)
        form.addRow("Origen:", source_row)

        root.addWidget(panel)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("Importar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona lista M3U", "", "Listas M3U (*.m3u *.m3u8);;Todos los archivos (*)"
        )
        if path:
            self.source_input.setText(path)

    def get_values(self):
        return self.type_combo.currentData(), self.source_input.text().strip()


class ExportPlaylistDialog(QDialog):
    """Vista previa editable antes de exportar TV y radio como M3U."""

    def __init__(self, entries: list[dict], parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Preparar lista M3U")
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Preparar exportación M3U",
            "Desmarca lo que no quieras incluir o edita nombre, URL y categoría. "
            "Los cambios solo afectan al archivo exportado, no a tu catálogo.",
        ))

        self.table = QTableWidget(len(entries), 5)
        self.table.setHorizontalHeaderLabels(["Incluir", "Tipo", "Nombre", "URL", "Categoría"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 68)
        self.table.setColumnWidth(1, 62)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 300)
        for row, entry in enumerate(entries):
            include = QTableWidgetItem()
            include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            include.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, include)
            kind = QTableWidgetItem("TV" if entry.get("type") == "tv" else "Radio")
            kind.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 1, kind)
            name = QTableWidgetItem(str(entry.get("name", "")))
            name.setData(Qt.UserRole, dict(entry))
            self.table.setItem(row, 2, name)
            self.table.setItem(row, 3, QTableWidgetItem(str(entry.get("url", ""))))
            self.table.setItem(
                row, 4, QTableWidgetItem(str(entry.get("group") or entry.get("tags") or ""))
            )
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        all_btn = QPushButton("Incluir todo")
        all_btn.clicked.connect(lambda: self._set_all_checked(Qt.Checked))
        actions.addWidget(all_btn)
        none_btn = QPushButton("No incluir nada")
        none_btn.clicked.connect(lambda: self._set_all_checked(Qt.Unchecked))
        actions.addWidget(none_btn)
        remove_btn = QPushButton("Quitar seleccionados")
        remove_btn.clicked.connect(self._remove_selected_rows)
        actions.addWidget(remove_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Elegir destino…")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def entries_for_export(self) -> list[dict]:
        entries = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() != Qt.Checked:
                continue
            base = dict(self.table.item(row, 2).data(Qt.UserRole) or {})
            base["name"] = self.table.item(row, 2).text().strip()
            base["url"] = self.table.item(row, 3).text().strip()
            group = self.table.item(row, 4).text().strip()
            if base.get("type") == "radio":
                base["tags"] = group
            else:
                base["group"] = group
            entries.append(base)
        return entries

    def _set_all_checked(self, state):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def _remove_selected_rows(self):
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)


class ManageChannelsDialog(QDialog):
    """
    Gestión de canales/emisoras en tres ámbitos, elegibles con un combo:

    - "Personalizados" -- los que el usuario añadió a mano o importó por
      M3U. Se pueden borrar de verdad (on_delete), igual que antes.
    - "Lista pública" -- los que vienen de iptv-org/Radio-Browser. No se
      pueden borrar (se descargan de nuevo en cada actualización), pero sí
      OCULTAR (on_hide) para que dejen de aparecer en las listas sin tocar
      la lista pública en sí -- pensado para los canales que vienen por
      defecto de otro país/región y no interesan.
    - "Ocultados" -- los que se ocultaron antes desde aquí. Se pueden
      RESTAURAR (on_unhide) en cualquier momento.

    El guardado real (disco + estado de la ventana) no vive aquí -- se pide
    al llamador vía on_delete(tipo, nombres) / on_hide(tipo, nombres) /
    on_unhide(tipo, nombres), igual que el resto de diálogos de este módulo
    dejan la persistencia a LibraryController. Los tres deben devolver
    cuántos se aplicaron de verdad, y este diálogo actualiza su propia
    lista visual con ese resultado sin tener que cerrarse.
    """

    _AMBITOS = [
        ("custom", "Personalizados (eliminar)"),
        ("public", "Lista pública (ocultar)"),
        ("hidden", "Ocultados (restaurar)"),
    ]

    def __init__(self, tv_datos: dict, radio_datos: dict, on_delete, on_hide, on_unhide,
                 entry_type: str = "tv", parent=None):
        """
        tv_datos / radio_datos: {"custom": [Channel/Station...],
        "public": [Channel/Station...], "hidden_names": set(str)|list(str)}.
        "public" debe venir ya SIN los ocultos (el llamador lo arma así),
        para no listar el mismo nombre a la vez en "Lista pública" y en
        "Ocultados".
        """
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Gestionar canales personalizados")
        self.setMinimumSize(560, 520)
        self._datos = {"tv": dict(tv_datos), "radio": dict(radio_datos)}
        for tipo in self._datos:
            self._datos[tipo]["hidden_names"] = set(self._datos[tipo].get("hidden_names") or ())
        self._on_delete = on_delete
        self._on_hide = on_hide
        self._on_unhide = on_unhide

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 18, 20, 18)
        root.addLayout(_header(
            "Gestionar canales personalizados",
            "Elige el tipo y el ámbito: borra tus canales personalizados, oculta "
            "canales de la lista pública que no quieras ver, o restaura los que "
            "ocultaste antes.",
        ))

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Canales de TV", "tv")
        self.type_combo.addItem("Emisoras de radio", "radio")
        idx = self.type_combo.findData(entry_type)
        self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.type_combo.currentIndexChanged.connect(self._reload_list)
        top_row.addWidget(self.type_combo)

        self.scope_combo = QComboBox()
        for valor, etiqueta in self._AMBITOS:
            self.scope_combo.addItem(etiqueta, valor)
        self.scope_combo.currentIndexChanged.connect(self._reload_list)
        top_row.addWidget(self.scope_combo)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filtrar por nombre…")
        self.filter_input.textChanged.connect(self._reload_list)
        top_row.addWidget(self.filter_input, stretch=1)
        root.addLayout(top_row)

        self.list_widget = QListWidget()
        self.list_widget.itemChanged.connect(self._update_count)
        root.addWidget(self.list_widget, stretch=1)

        sel_row = QHBoxLayout()
        select_all_btn = QPushButton("Seleccionar todo")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        sel_row.addWidget(select_all_btn)
        select_none_btn = QPushButton("Ninguno")
        select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        sel_row.addWidget(select_none_btn)
        sel_row.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("dialogSubtitle")
        sel_row.addWidget(self.count_label)
        root.addLayout(sel_row)

        buttons = QDialogButtonBox()
        # self.action_btn tiene que existir ANTES de la primera llamada a
        # _reload_list() de más abajo -- _reload_list() dispara
        # _update_count(), que lo habilita/deshabilita según haya algo
        # marcado. Con el orden invertido, esa primera llamada revienta con
        # AttributeError dentro de __init__ y todo el diálogo se queda sin
        # construir -- "le pincho pero no hace nada", sin ningún error
        # visible porque PySide se traga la excepción de un slot de menú y
        # sigue funcionando como si nada (ver bug ya resuelto con delete_btn).
        self.action_btn = buttons.addButton("Eliminar seleccionados", QDialogButtonBox.AcceptRole)
        self.action_btn.clicked.connect(self._on_action_clicked)
        close_btn = buttons.addButton("Cerrar", QDialogButtonBox.RejectRole)
        close_btn.clicked.connect(self.accept)  # cerrar no deshace lo ya aplicado

        self._reload_list()

        root.addWidget(buttons)

    # ---------- listado ----------

    def _current_names(self):
        tipo = self.type_combo.currentData()
        ambito = self.scope_combo.currentData()
        datos_tipo = self._datos[tipo]
        if ambito == "custom":
            nombres = [c.name for c in datos_tipo["custom"]]
        elif ambito == "public":
            nombres = [c.name for c in datos_tipo["public"]]
        else:
            nombres = sorted(datos_tipo["hidden_names"])
        return tipo, ambito, nombres

    def _reload_list(self):
        _tipo, _ambito, nombres = self._current_names()
        filtro = self.filter_input.text().strip().casefold()

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for nombre in nombres:
            if filtro and filtro not in nombre.casefold():
                continue
            item = QListWidgetItem(nombre)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, nombre)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._update_action_button()
        self._update_count()

    def _set_all_checked(self, checked: bool):
        estado = Qt.Checked if checked else Qt.Unchecked
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(estado)
        self.list_widget.blockSignals(False)
        self._update_count()

    def _update_action_button(self):
        _tipo, ambito, _nombres = self._current_names()
        if ambito == "custom":
            texto, color = "Eliminar seleccionados", palette.DANGER
        elif ambito == "public":
            texto, color = "Ocultar seleccionados", palette.ACCENT_CATEGORY_ORANGE
        else:
            texto, color = "Restaurar seleccionados", palette.SUCCESS
        self.action_btn.setText(texto)
        self.action_btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; font-weight: 700; }}"
        )

    def _update_count(self, *_ignorar):
        total = self.list_widget.count()
        marcados = sum(
            1 for i in range(total)
            if self.list_widget.item(i).checkState() == Qt.Checked
        )
        if total == 0:
            _tipo, ambito, _nombres = self._current_names()
            mensajes = {
                "custom": "No hay entradas personalizadas de este tipo.",
                "public": "No hay canales públicos que mostrar (o están todos ocultos).",
                "hidden": "No has ocultado ninguno todavía.",
            }
            self.count_label.setText(mensajes.get(ambito, ""))
        else:
            self.count_label.setText(f"{marcados} de {total} seleccionados")
        self.action_btn.setEnabled(marcados > 0)

    # ---------- acción: borrar / ocultar / restaurar ----------

    def _on_action_clicked(self):
        tipo, ambito, _nombres = self._current_names()
        seleccionados = [
            self.list_widget.item(i).data(Qt.UserRole)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).checkState() == Qt.Checked
        ]
        if not seleccionados:
            return

        etiqueta = "canales" if tipo == "tv" else "emisoras"
        datos_tipo = self._datos[tipo]
        borrados = set(seleccionados)

        if ambito == "custom":
            if QMessageBox.question(
                self, "Eliminar seleccionados",
                f"Vas a eliminar {len(seleccionados)} {etiqueta} de tu lista personalizada. "
                "Esto no se puede deshacer desde aquí.\n\n¿Continuar?",
            ) != QMessageBox.Yes:
                return
            self._on_delete(tipo, seleccionados)
            datos_tipo["custom"] = [c for c in datos_tipo["custom"] if c.name not in borrados]

        elif ambito == "public":
            if QMessageBox.question(
                self, "Ocultar seleccionados",
                f"Vas a ocultar {len(seleccionados)} {etiqueta} de la lista pública. "
                "Podrás volver a mostrarlos desde \"Ocultados\" cuando quieras.\n\n¿Continuar?",
            ) != QMessageBox.Yes:
                return
            self._on_hide(tipo, seleccionados)
            datos_tipo["public"] = [c for c in datos_tipo["public"] if c.name not in borrados]
            datos_tipo["hidden_names"] |= borrados

        else:  # "hidden" -- restaurar es reversible e inofensivo, sin confirmación
            self._on_unhide(tipo, seleccionados)
            datos_tipo["hidden_names"] -= borrados

        self._reload_list()

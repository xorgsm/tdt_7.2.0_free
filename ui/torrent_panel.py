"""
Pestaña "Torrents" del panel de Descargas — vía libtorrent embebido en el
propio proceso de la app. Estilo inspirado en Transmission: barra de
herramientas con iconos (añadir archivo/enlace, reanudar, pausar, quitar,
información), un filtro "Mostrar:" con dos desplegables (estado y orden) y
una lista única donde cada torrent enseña progreso, tamaño, tiempo
restante, pares conectados y velocidad — aunque por debajo sigue siendo
libtorrent, no Transmission ni qBittorrent.

Coder By X@R
"""
import os
import subprocess

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from core.torrent_client import TorrentClient, paquete_disponible
from core import torrent_history
from ui.visual import set_variant, set_visual_state

ESTADOS_LEGIBLES = {
    "downloading": "Descargando",
    "stalledDL": "Esperando peers",
    "metaDL": "Obteniendo metadatos",
    "pausedDL": "Pausado",
    "queuedDL": "En cola",
    "checkingDL": "Comprobando",
    "uploading": "Completo (compartiendo)",
    "stalledUP": "Completo (compartiendo)",
    "pausedUP": "Completo (pausado)",
    "queuedUP": "En cola (completo)",
    "error": "Error",
    "missingFiles": "Archivos no encontrados",
}

# Estados que cuentan como "ya terminó de descargar" — se mueven a la
# lista de completados en vez de quedarse en la de activos.
ESTADOS_COMPLETADOS = {"stalledUP", "pausedUP", "queuedUP", "uploading"}

# Filtro "Mostrar:" (igual que el desplegable de estado de Transmission) y
# orden de la lista (segundo desplegable). Los valores son las claves; el
# texto con el recuento se recalcula en cada repintado.
FILTROS = ("Todos", "Descargando", "Pausados", "Completados", "Error")
ORDENES = ("Nombre", "Progreso", "Velocidad", "Tamaño")

ROLE_HASH = Qt.UserRole
ROLE_COMPLETADO = Qt.UserRole + 1
ROLE_PATH = Qt.UserRole + 2

def _formatear_velocidad(bytes_seg: int) -> str:
    if bytes_seg <= 0:
        return "0 B/s"
    kb = bytes_seg / 1024
    if kb < 1024:
        return f"{kb:.0f} KB/s"
    return f"{kb / 1024:.1f} MB/s"


def _formatear_tamano(bytes_total: int) -> str:
    if bytes_total <= 0:
        return ""
    mb = bytes_total / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.0f} MB"
    return f"{mb / 1024:.2f} GB"


def _formatear_eta(segundos: int) -> str:
    if segundos is None or segundos < 0:
        return ""
    if segundos < 60:
        return "falta menos de 1 min"
    minutos = segundos // 60
    if minutos < 60:
        return f"falta {minutos} min"
    horas = minutos // 60
    if horas < 48:
        return f"falta {horas} horas" if horas != 1 else "falta 1 hora"
    return f"falta {horas // 24} días"


def _bucket_estado(state: str) -> str:
    """A qué grupo del filtro "Mostrar:" pertenece un estado de torrent."""
    if state in ESTADOS_COMPLETADOS:
        return "Completados"
    if state == "pausedDL":
        return "Pausados"
    if state == "error":
        return "Error"
    return "Descargando"  # downloading, stalledDL, metaDL, queuedDL, checkingDL


def _separador_vertical() -> QFrame:
    linea = QFrame()
    linea.setObjectName("mediaSeparator")
    linea.setFrameShape(QFrame.VLine)
    return linea


class _ConnectWorker(QThread):
    """Conectar con el motor de torrents puede tardar (unos segundos al
    arrancar el proceso) — en un hilo aparte para no congelar la interfaz."""
    done = Signal(object)  # str del error, o None si OK

    def __init__(self, client: TorrentClient, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        error = self.client.conectar()
        self.done.emit(error)


class TorrentPanel(QWidget):
    def __init__(self, dest_dir: str, on_dest_changed=None, parent=None):
        super().__init__(parent)
        self.setObjectName("torrentPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self.dest_dir = dest_dir
        self.on_dest_changed = on_dest_changed
        self.client = TorrentClient()
        self._connect_worker = None

        # Datos en bruto (no widgets): se repintan enteros en cada refresco
        # o cambio de filtro/orden -- con como mucho unas pocas decenas de
        # torrents y un refresco cada 2s, reconstruir la lista entera sale
        # más simple y igual de barato que ir parcheando filas una a una.
        self._activos = {}       # hash -> dict con name/state/progress/...
        self._completados = []   # [{"name","path","size"}, ...] recientes primero
        self._completados_ya_guardados = set()  # hashes ya persistidos esta sesión
        self._hash_seleccionado = None

        self._build_ui()
        self._cargar_historial_persistente()
        self._repintar_lista()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._refrescar_lista)

        if paquete_disponible():
            self._conectar()
        else:
            self._set_status(
                "No se encontró el motor de torrents (libtorrent) empaquetado "
                "con esta aplicación. Si compilaste tú el .exe, revisa que la "
                "dependencia 'libtorrent' esté instalada antes de compilar.",
                error=True,
            )

    # ---------- construcción ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # ---- Barra de herramientas (estilo Transmission) ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.add_file_btn = self._boton_toolbar("📄", "Añadir torrent desde archivo…")
        set_variant(self.add_file_btn, "primary")
        self.add_file_btn.clicked.connect(self._anadir_desde_archivo)
        toolbar.addWidget(self.add_file_btn)

        self.add_url_btn = self._boton_toolbar("🧲", "Añadir torrent desde enlace magnet o URL…")
        set_variant(self.add_url_btn, "primary")
        self.add_url_btn.clicked.connect(self._anadir_desde_dialogo)
        toolbar.addWidget(self.add_url_btn)

        toolbar.addWidget(_separador_vertical())

        self.start_btn = self._boton_toolbar("▶", "Reanudar el torrent seleccionado")
        self.start_btn.clicked.connect(self._reanudar_seleccionado)
        toolbar.addWidget(self.start_btn)

        self.pause_btn = self._boton_toolbar("⏸", "Pausar el torrent seleccionado")
        self.pause_btn.clicked.connect(self._pausar_seleccionado)
        toolbar.addWidget(self.pause_btn)

        self.remove_btn = self._boton_toolbar("➖", "Quitar el torrent seleccionado")
        set_variant(self.remove_btn, "danger")
        self.remove_btn.clicked.connect(self._eliminar_seleccionado)
        toolbar.addWidget(self.remove_btn)

        toolbar.addWidget(_separador_vertical())

        self.info_btn = self._boton_toolbar("ℹ", "Información del torrent seleccionado")
        set_variant(self.info_btn, "info")
        self.info_btn.clicked.connect(self._mostrar_info_seleccionado)
        toolbar.addWidget(self.info_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # ---- Filtro "Mostrar:" ----
        filtro_row = QHBoxLayout()
        filtro_row.setSpacing(6)
        lbl_mostrar = QLabel("Mostrar:")
        lbl_mostrar.setObjectName("mediaMeta")
        filtro_row.addWidget(lbl_mostrar)

        self.filtro_combo = QComboBox()
        self.filtro_combo.setObjectName("groupFilter")
        for clave in FILTROS:
            self.filtro_combo.addItem(clave, clave)
        self.filtro_combo.currentIndexChanged.connect(self._repintar_lista)
        filtro_row.addWidget(self.filtro_combo)

        self.orden_combo = QComboBox()
        self.orden_combo.setObjectName("groupFilter")
        for clave in ORDENES:
            self.orden_combo.addItem(clave, clave)
        self.orden_combo.currentIndexChanged.connect(self._repintar_lista)
        filtro_row.addWidget(self.orden_combo)

        filtro_row.addStretch(1)
        layout.addLayout(filtro_row)

        # ---- Carpeta destino ----
        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)

        lbl = QLabel("Carpeta:")
        lbl.setObjectName("mediaMeta")
        dest_row.addWidget(lbl)

        self.dest_label = QLabel(self.dest_dir)
        self.dest_label.setObjectName("mediaPath")
        self.dest_label.setMaximumWidth(320)
        dest_row.addWidget(self.dest_label, stretch=1)

        cambiar_btn = QPushButton("Cambiar")
        cambiar_btn.setCursor(Qt.PointingHandCursor)
        cambiar_btn.setFixedHeight(26)
        cambiar_btn.setFixedWidth(72)
        set_variant(cambiar_btn, "secondary")
        cambiar_btn.clicked.connect(self._cambiar_carpeta)
        dest_row.addWidget(cambiar_btn)

        abrir_btn = QPushButton("Abrir")
        abrir_btn.setCursor(Qt.PointingHandCursor)
        abrir_btn.setFixedHeight(26)
        abrir_btn.setFixedWidth(60)
        set_variant(abrir_btn, "secondary")
        abrir_btn.clicked.connect(lambda: self._abrir_ruta(self.dest_dir))
        dest_row.addWidget(abrir_btn)

        layout.addLayout(dest_row)

        self.status_label = QLabel("Conectando con el motor de torrents…")
        self.status_label.setObjectName("mediaStatus")
        set_visual_state(self.status_label, "loading")
        layout.addWidget(self.status_label)

        # ---- Lista única (activos + completados, filtrada/ordenada) ----
        self.torrent_list = QListWidget()
        self.torrent_list.setObjectName("channelList")
        self.torrent_list.itemSelectionChanged.connect(self._on_seleccion_cambiada)
        self.torrent_list.itemDoubleClicked.connect(self._on_doble_click)
        layout.addWidget(self.torrent_list, stretch=1)

        self._actualizar_estado_botones_toolbar()

    @staticmethod
    def _boton_toolbar(texto: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(texto)
        btn.setToolTip(tooltip)
        btn.setFixedSize(34, 34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setObjectName("mediaToolbarButton")
        set_variant(btn, "secondary")
        return btn

    def _set_status(self, texto: str, error: bool = False):
        self.status_label.setText(texto)
        set_visual_state(self.status_label, "error" if error else "default")

    # ---------- carpeta destino ----------

    def _cambiar_carpeta(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Selecciona carpeta de descargas de torrents", self.dest_dir
        )
        if directory:
            self.set_dest_dir(directory)
            if self.on_dest_changed:
                self.on_dest_changed(directory)

    def _abrir_ruta(self, path: str):
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
            QMessageBox.information(self, "No encontrado", "Esa carpeta ya no existe.")

    # ---------- conexión ----------

    def _conectar(self):
        if self._connect_worker is not None and self._connect_worker.isRunning():
            return
        self._set_status("Conectando con el motor de torrents…")
        self._connect_worker = _ConnectWorker(self.client, self)
        self._connect_worker.done.connect(self._on_conectado)
        self._connect_worker.start()

    def _on_conectado(self, error):
        if error:
            self._set_status(error, error=True)
            self._poll_timer.stop()
            return
        self._set_status("Motor de torrents listo.")
        self._poll_timer.start()
        self._refrescar_lista()

    # ---------- añadir torrents ----------

    def _anadir_desde_dialogo(self):
        """Equivalente al icono "Abrir URL" (el globo) de Transmission:
        un diálogo para pegar un magnet o una URL, en vez de un cuadro de
        texto fijo siempre visible en la pestaña."""
        texto, ok = QInputDialog.getText(
            self, "Añadir torrent", "Enlace magnet o URL del .torrent:"
        )
        texto = (texto or "").strip()
        if ok and texto:
            self._anadir(texto)

    def _anadir_desde_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir archivo .torrent", "", "Archivos .torrent (*.torrent)"
        )
        if ruta:
            self._anadir(ruta)

    def _anadir(self, magnet_o_ruta: str):
        if not self.client.conectado:
            QMessageBox.warning(
                self, "No conectado",
                "El motor de torrents todavía no está listo. Espera unos "
                "segundos a que arranque y vuelve a intentarlo."
            )
            return
        error = self.client.anadir(magnet_o_ruta, self.dest_dir)
        if error:
            QMessageBox.warning(self, "No se pudo añadir el torrent", error)
            return
        self._set_status("Torrent añadido.")
        self._refrescar_lista()

    # ---------- refresco de datos ----------

    def _refrescar_lista(self):
        if not self.client.conectado:
            return
        torrents = self.client.listar()

        activos_nuevos = {}
        for t in torrents:
            if t.state in ESTADOS_COMPLETADOS:
                if t.hash not in self._completados_ya_guardados:
                    self._completados_ya_guardados.add(t.hash)
                    ruta = os.path.join(self.dest_dir, t.name)
                    self._completados.insert(0, {"name": t.name, "path": ruta, "size": t.size})
                    torrent_history.add_entry(t.name, ruta, t.size)
                continue
            activos_nuevos[t.hash] = {
                "name": t.name, "state": t.state, "progress": t.progress,
                "size": t.size, "dlspeed": t.dlspeed, "upspeed": t.upspeed,
                "peers": t.peers, "eta": t.eta,
            }
        self._activos = activos_nuevos
        self._repintar_lista()

    # ---------- repintado (filtro + orden + reconstrucción de la lista) ----------

    def _repintar_lista(self):
        filtro = self.filtro_combo.currentData() or "Todos"
        orden = self.orden_combo.currentData() or "Nombre"

        activos = list(self._activos.items())
        if filtro == "Completados":
            activos = []
        elif filtro != "Todos":
            activos = [(h, info) for h, info in activos if _bucket_estado(info["state"]) == filtro]

        completados = list(enumerate(self._completados)) if filtro in ("Todos", "Completados") else []

        if orden == "Progreso":
            activos.sort(key=lambda item: -item[1]["progress"])
        elif orden == "Velocidad":
            activos.sort(key=lambda item: -item[1]["dlspeed"])
        elif orden == "Tamaño":
            activos.sort(key=lambda item: -item[1]["size"])
            completados.sort(key=lambda item: -item[1]["size"])
        else:  # Nombre
            activos.sort(key=lambda item: item[1]["name"].lower())
            completados.sort(key=lambda item: item[1]["name"].lower())

        self.torrent_list.blockSignals(True)
        self.torrent_list.clear()
        for h, info in activos:
            self._agregar_fila_activo(h, info)
        for _, info in completados:
            self._agregar_fila_completado(info)
        self.torrent_list.blockSignals(False)

        # Mantener la selección de una posible actualización anterior, para
        # que los botones de la barra de herramientas no "parpadeen"
        # deshabilitados cada 2 segundos por culpa del refresco periódico.
        if self._hash_seleccionado:
            for i in range(self.torrent_list.count()):
                item = self.torrent_list.item(i)
                if item.data(ROLE_HASH) == self._hash_seleccionado:
                    self.torrent_list.setCurrentItem(item)
                    break
            else:
                self._hash_seleccionado = None

        self._actualizar_texto_filtro()
        self._actualizar_estado_botones_toolbar()

    def _actualizar_texto_filtro(self):
        """Recalcula los recuentos "Todos (3)" del desplegable de estado,
        igual que hace Transmission junto a cada opción del filtro."""
        recuentos = {"Todos": len(self._activos) + len(self._completados), "Completados": len(self._completados)}
        for info in self._activos.values():
            bucket = _bucket_estado(info["state"])
            recuentos[bucket] = recuentos.get(bucket, 0) + 1

        for i, clave in enumerate(FILTROS):
            self.filtro_combo.setItemText(i, f"{clave} ({recuentos.get(clave, 0)})")

    def _agregar_fila_activo(self, hash_: str, info: dict):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 6, 10, 6)
        row_layout.setSpacing(10)

        icono = {"Descargando": "⬇", "Pausados": "⏸", "Error": "⚠"}.get(_bucket_estado(info["state"]), "⏳")
        icon_label = QLabel(icono)
        icon_label.setObjectName("mediaRowIcon")
        icon_label.setFixedWidth(28)
        row_layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        name_label = QLabel(info["name"])
        name_label.setObjectName("mediaRowTitle")
        text_col.addWidget(name_label)

        progress = QProgressBar()
        progress.setObjectName("mediaProgress")
        progress.setRange(0, 100)
        progress.setValue(int(info["progress"] * 100))
        progress.setTextVisible(False)
        progress.setFixedHeight(8)
        text_col.addWidget(progress)

        hecho = _formatear_tamano(info["size"] * info["progress"])
        total = _formatear_tamano(info["size"])
        porcentaje = info["progress"] * 100
        eta_txt = _formatear_eta(info["eta"])
        linea1 = f"{hecho} de {total} ({porcentaje:.1f}%)" if total else f"{porcentaje:.1f}%"
        if eta_txt:
            linea1 += f" - {eta_txt}"
        linea1_label = QLabel(linea1)
        linea1_label.setObjectName("mediaRowMeta")
        text_col.addWidget(linea1_label)

        estado_txt = ESTADOS_LEGIBLES.get(info["state"], info["state"])
        linea2 = (
            f"{estado_txt} · {info['peers']} pares conectados · "
            f"{_formatear_velocidad(info['dlspeed'])}↓ {_formatear_velocidad(info['upspeed'])}↑"
        )
        linea2_label = QLabel(linea2)
        linea2_label.setObjectName("mediaRowDetail")
        text_col.addWidget(linea2_label)

        row_layout.addLayout(text_col, stretch=1)

        item = QListWidgetItem()
        item.setData(ROLE_HASH, hash_)
        item.setData(ROLE_COMPLETADO, False)
        item.setSizeHint(row.sizeHint())
        self.torrent_list.addItem(item)
        self.torrent_list.setItemWidget(item, row)

    def _agregar_fila_completado(self, info: dict):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 6, 10, 6)
        row_layout.setSpacing(10)

        icon_label = QLabel("✅")
        icon_label.setObjectName("mediaRowIcon")
        icon_label.setFixedWidth(28)
        row_layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        texto_nombre = info["name"]
        if info.get("size"):
            texto_nombre += f"  ·  {_formatear_tamano(info['size'])}"
        name_label = QLabel(texto_nombre)
        name_label.setObjectName("mediaRowTitle")
        text_col.addWidget(name_label)

        ruta_label = QLabel(f"Completado · {info['path']}")
        ruta_label.setObjectName("mediaRowDetail")
        text_col.addWidget(ruta_label)

        row_layout.addLayout(text_col, stretch=1)

        abrir_btn = QPushButton("Abrir")
        abrir_btn.setFixedHeight(26)
        abrir_btn.setFixedWidth(56)
        abrir_btn.setCursor(Qt.PointingHandCursor)
        abrir_btn.setToolTip("Ver en la carpeta del explorador")
        set_variant(abrir_btn, "secondary")
        abrir_btn.clicked.connect(lambda: self._abrir_ruta(info["path"]))
        row_layout.addWidget(abrir_btn)

        item = QListWidgetItem()
        item.setData(ROLE_COMPLETADO, True)
        item.setData(ROLE_PATH, info["path"])
        item.setSizeHint(row.sizeHint())
        self.torrent_list.addItem(item)
        self.torrent_list.setItemWidget(item, row)

    # ---------- selección y acciones de la barra de herramientas ----------

    def _on_seleccion_cambiada(self):
        item = self.torrent_list.currentItem()
        self._hash_seleccionado = item.data(ROLE_HASH) if item and not item.data(ROLE_COMPLETADO) else None
        self._actualizar_estado_botones_toolbar()

    def _item_seleccionado(self):
        return self.torrent_list.currentItem()

    def _actualizar_estado_botones_toolbar(self):
        item = self._item_seleccionado()
        hay_activo = bool(item and not item.data(ROLE_COMPLETADO))
        hay_algo = item is not None
        pausado = hay_activo and self._activos.get(item.data(ROLE_HASH), {}).get("state") == "pausedDL"
        self.start_btn.setEnabled(hay_activo and pausado)
        self.pause_btn.setEnabled(hay_activo and not pausado)
        self.remove_btn.setEnabled(hay_algo)
        self.info_btn.setEnabled(hay_algo)

    def _reanudar_seleccionado(self):
        item = self._item_seleccionado()
        if item and not item.data(ROLE_COMPLETADO):
            self.client.reanudar(item.data(ROLE_HASH))
            QTimer.singleShot(400, self._refrescar_lista)

    def _pausar_seleccionado(self):
        item = self._item_seleccionado()
        if item and not item.data(ROLE_COMPLETADO):
            self.client.pausar(item.data(ROLE_HASH))
            QTimer.singleShot(400, self._refrescar_lista)

    def _eliminar_seleccionado(self):
        item = self._item_seleccionado()
        if item is None:
            return
        if item.data(ROLE_COMPLETADO):
            self._eliminar_completado(item.data(ROLE_PATH))
        else:
            self._eliminar_activo(item.data(ROLE_HASH))

    def _eliminar_activo(self, hash_: str):
        respuesta = QMessageBox.question(
            self, "Quitar torrent",
            "¿Quitar este torrent de la lista? Puedes conservar o borrar "
            "también los archivos ya descargados.\n\n"
            "Sí = borrar también los archivos\nNo = solo quitar de la lista",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if respuesta == QMessageBox.Cancel:
            return
        self.client.eliminar(hash_, borrar_archivos=(respuesta == QMessageBox.Yes))
        self._hash_seleccionado = None
        self._refrescar_lista()

    def _eliminar_completado(self, ruta: str):
        entrada = next((c for c in self._completados if c["path"] == ruta), None)
        if entrada is None:
            return
        respuesta = QMessageBox.question(
            self, "Quitar del historial",
            f"¿Quitar «{entrada['name']}» de la lista de completados?\n\n"
            "El archivo descargado no se borra, solo deja de aparecer aquí.",
        )
        if respuesta != QMessageBox.Yes:
            return
        self._completados = [c for c in self._completados if c["path"] != ruta]
        torrent_history.remove_entry(entrada["name"], ruta)
        self._repintar_lista()

    def _mostrar_info_seleccionado(self):
        item = self._item_seleccionado()
        if item is None:
            return
        if item.data(ROLE_COMPLETADO):
            ruta = item.data(ROLE_PATH)
            entrada = next((c for c in self._completados if c["path"] == ruta), None)
            if entrada is None:
                return
            QMessageBox.information(
                self, "Información del torrent",
                f"{entrada['name']}\n\n"
                f"Tamaño: {_formatear_tamano(entrada.get('size', 0)) or 'desconocido'}\n"
                f"Guardado en: {entrada['path']}\n"
                "Estado: completado"
            )
            return

        info = self._activos.get(item.data(ROLE_HASH))
        if info is None:
            return
        QMessageBox.information(
            self, "Información del torrent",
            f"{info['name']}\n\n"
            f"Estado: {ESTADOS_LEGIBLES.get(info['state'], info['state'])}\n"
            f"Progreso: {info['progress'] * 100:.1f}%\n"
            f"Tamaño: {_formatear_tamano(info['size']) or 'desconocido'}\n"
            f"Velocidad: {_formatear_velocidad(info['dlspeed'])}↓ "
            f"{_formatear_velocidad(info['upspeed'])}↑\n"
            f"Pares conectados: {info['peers']}\n"
            f"Carpeta destino: {self.dest_dir}"
        )

    def _on_doble_click(self, item: QListWidgetItem):
        if item.data(ROLE_COMPLETADO):
            self._abrir_ruta(item.data(ROLE_PATH))
        else:
            self._mostrar_info_seleccionado()

    # ---------- historial de completados ----------

    def _cargar_historial_persistente(self):
        """
        Puebla la lista de completados con lo guardado en sesiones
        anteriores. libtorrent (igual que aria2 antes) no recuerda nada entre
        arranques del proceso, así que sin esto la lista de "Completados" se
        vaciaba cada vez que se cerraba la app — ahora sobrevive, igual que
        el historial de canales.
        """
        self._completados = [
            {"name": e["name"], "path": e["path"], "size": e.get("size", 0)}
            for e in torrent_history.load_history()
        ]

    # ---------- carpeta destino (compartida con el resto del panel) ----------

    def set_dest_dir(self, path: str):
        self.dest_dir = path
        self.dest_label.setText(path)

    # ---------- cierre ----------

    def shutdown(self, on_wait=None):
        self._poll_timer.stop()
        # cerrar() primero (ver el mismo orden y motivo en
        # ui/soulseek_panel.py): marca al cliente como cerrándose antes de
        # esperar a _connect_worker, para que conectar() no pueda crear una
        # sesión de libtorrent nueva justo después de este cierre.
        self.client.cerrar(on_wait=on_wait)
        if self._connect_worker is not None and self._connect_worker.isRunning():
            self._connect_worker.wait(1000)

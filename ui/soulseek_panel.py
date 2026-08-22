"""
Pestaña "Soulseek" del panel de Descargas -- habla por HTTP con un
proceso externo slskd (nunca empaquetado ni enlazado: es AGPLv3, ver
docs/superpowers/specs/2026-08-18-integracion-soulseek-design.md). Solo
búsqueda y descarga (v1); no comparte carpetas propias.

Coder By X@R
"""
import os
import subprocess

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from core import soulseek_account
from core.soulseek_client import SoulseekClient, ensure_slskd
from ui.visual import set_variant, set_visual_state

ROLE_RESULT = Qt.UserRole
ROLE_DOWNLOAD_ID = Qt.UserRole + 1

_INTENTOS_LOGIN_MAX = 15


def _formatear_tamano(bytes_total: int) -> str:
    if bytes_total <= 0:
        return ""
    mb = bytes_total / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.0f} MB"
    return f"{mb / 1024:.2f} GB"


_ESTADOS_TERMINALES = ("Completed", "Errored", "Cancelled", "Rejected")


def _esta_activa(descarga: dict) -> bool:
    """Una descarga sigue viva (y por tanto se puede cancelar) mientras
    slskd no la haya marcado con ninguno de sus estados terminales."""
    return not any(x in descarga["state"] for x in _ESTADOS_TERMINALES)


def _formatear_velocidad(bytes_seg) -> str:
    if not bytes_seg or bytes_seg <= 0:
        return "0 B/s"
    kb = bytes_seg / 1024
    if kb < 1024:
        return f"{kb:.0f} KB/s"
    return f"{kb / 1024:.1f} MB/s"


class _CuentaSoulseekDialog(QDialog):
    """Pide usuario/contraseña de Soulseek. No hay paso de registro
    aparte en la red: un usuario/contraseña nuevos se crean solos la
    primera vez que se conectan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cuenta de Soulseek")
        self.setMinimumWidth(380)
        self.result_data = None

        layout = QVBoxLayout(self)
        info = QLabel(
            "Introduce un usuario y contraseña para la red Soulseek. Si no "
            "existen todavía, se crean solos al conectar por primera vez."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.user_input = QLineEdit()
        form.addRow("Usuario:", self.user_input)
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        form.addRow("Contraseña:", self.pass_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        username = self.user_input.text().strip()
        password = self.pass_input.text()
        if not username or not password:
            QMessageBox.warning(self, "Faltan datos", "Usuario y contraseña son obligatorios.")
            return
        self.result_data = (username, password)
        self.accept()


class _EnsureWorker(QThread):
    """Descargar slskd (si falta) y arrancarlo puede tardar -- en un hilo
    aparte para no congelar la interfaz, igual que _ConnectWorker en
    ui/torrent_panel.py."""
    done = Signal(object)  # str del error, o None si OK

    def __init__(self, username: str, password: str, dest_dir: str, client: SoulseekClient, parent=None):
        super().__init__(parent)
        self.username = username
        self.password = password
        self.dest_dir = dest_dir
        self.client = client

    def run(self):
        try:
            ensure_slskd()
        except Exception as exc:
            self.done.emit(f"No se pudo descargar slskd: {exc}")
            return
        self.done.emit(self.client.conectar(self.username, self.password, self.dest_dir))


class _SearchWorker(QThread):
    done = Signal(list)

    def __init__(self, client: SoulseekClient, texto: str, parent=None):
        super().__init__(parent)
        self.client = client
        self.texto = texto

    def run(self):
        try:
            resultados = self.client.buscar(self.texto)
        except Exception:
            resultados = []
        self.done.emit(resultados)


class SoulseekPanel(QWidget):
    def __init__(self, dest_dir: str, on_dest_changed=None, parent=None):
        super().__init__(parent)
        self.setObjectName("soulseekPanel")
        self.setProperty("uiSurface", "mediaPanel")
        self.dest_dir = dest_dir
        self.on_dest_changed = on_dest_changed
        self.client = SoulseekClient()
        self._ensure_worker = None
        self._search_worker = None
        self._intentos_login = 0

        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._refrescar_descargas)

        self._login_timer = QTimer(self)
        self._login_timer.setInterval(1000)
        self._login_timer.timeout.connect(self._comprobar_login)

        self._iniciar_sesion_si_hay_cuenta()

    # ---------- construcción ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar en Soulseek…")
        self.search_input.returnPressed.connect(self._buscar)
        search_row.addWidget(self.search_input, stretch=1)

        self.search_btn = QPushButton("Buscar")
        set_variant(self.search_btn, "primary")
        self.search_btn.clicked.connect(self._buscar)
        search_row.addWidget(self.search_btn)

        self.connect_btn = QPushButton("Conectar cuenta")
        set_variant(self.connect_btn, "secondary")
        self.connect_btn.clicked.connect(self._pedir_cuenta_y_conectar)
        search_row.addWidget(self.connect_btn)

        layout.addLayout(search_row)

        self.status_label = QLabel("Sin cuenta de Soulseek configurada.")
        self.status_label.setObjectName("mediaStatus")
        layout.addWidget(self.status_label)

        results_header = QHBoxLayout()
        results_header.addWidget(QLabel("Resultados:"))
        results_header.addStretch(1)
        self.select_all_check = QCheckBox("Marcar todos")
        self.select_all_check.toggled.connect(self._marcar_todos)
        results_header.addWidget(self.select_all_check)
        self.download_selected_btn = QPushButton("Descargar seleccionados")
        set_variant(self.download_selected_btn, "secondary")
        self.download_selected_btn.clicked.connect(self._descargar_seleccionados)
        results_header.addWidget(self.download_selected_btn)
        layout.addLayout(results_header)

        self.results_list = QListWidget()
        self.results_list.setObjectName("channelList")
        layout.addWidget(self.results_list, stretch=1)

        downloads_header = QHBoxLayout()
        downloads_header.addWidget(QLabel("Descargas:"))
        downloads_header.addStretch(1)
        self.cancel_all_btn = QPushButton("Cancelar todas")
        set_variant(self.cancel_all_btn, "secondary")
        # Arranca apagado: todavía no se ha consultado a slskd, así que no
        # se sabe si hay descargas vivas. _actualizar_resumen_descargas() lo
        # enciende/apaga en cada refresco.
        self.cancel_all_btn.setEnabled(False)
        self.cancel_all_btn.clicked.connect(self._cancelar_todas)
        downloads_header.addWidget(self.cancel_all_btn)

        self.clear_completed_btn = QPushButton("Borrar completadas")
        set_variant(self.clear_completed_btn, "secondary")
        self.clear_completed_btn.setEnabled(False)
        self.clear_completed_btn.clicked.connect(self._borrar_completadas)
        downloads_header.addWidget(self.clear_completed_btn)
        layout.addLayout(downloads_header)

        self.downloads_summary_label = QLabel("")
        self.downloads_summary_label.setObjectName("mediaRowDetail")
        layout.addWidget(self.downloads_summary_label)
        self.downloads_list = QListWidget()
        self.downloads_list.setObjectName("channelList")
        layout.addWidget(self.downloads_list, stretch=1)

    def _set_status(self, texto: str, error: bool = False, loading: bool = False):
        self.status_label.setText(texto)
        estado = "error" if error else ("loading" if loading else "default")
        set_visual_state(self.status_label, estado)

    # ---------- conexión ----------

    def _iniciar_sesion_si_hay_cuenta(self):
        cuenta = soulseek_account.load_account()
        if cuenta is None:
            self._set_status(
                "Sin cuenta de Soulseek configurada. Pulsa «Conectar cuenta» "
                "para empezar."
            )
            return
        self._conectar(cuenta["username"], cuenta["password"])

    def _pedir_cuenta_y_conectar(self):
        dialogo = _CuentaSoulseekDialog(self)
        if dialogo.exec() != QDialog.Accepted or dialogo.result_data is None:
            return
        username, password = dialogo.result_data
        soulseek_account.save_account(username, password)
        self._conectar(username, password)

    def _conectar(self, username: str, password: str):
        if self._ensure_worker is not None and self._ensure_worker.isRunning():
            return
        self._set_status("Conectando con Soulseek (puede tardar la primera vez)…", loading=True)
        self._ensure_worker = _EnsureWorker(username, password, self.dest_dir, self.client, self)
        self._ensure_worker.done.connect(self._on_conectado)
        self._ensure_worker.start()

    def _on_conectado(self, error):
        if error:
            self._set_status(error, error=True)
            return
        self.connect_btn.setVisible(False)
        self._set_status("Iniciando sesión en Soulseek…", loading=True)
        self._intentos_login = 0
        self._login_timer.start()
        self._poll_timer.start()

    def _comprobar_login(self):
        self._intentos_login += 1
        if self.client.esta_logueado():
            self._login_timer.stop()
            self._set_status("Conectado a Soulseek.")
            return
        if self._intentos_login >= _INTENTOS_LOGIN_MAX:
            self._login_timer.stop()
            self._set_status(
                "No se pudo iniciar sesión en Soulseek. Comprueba tu usuario "
                "y contraseña.", error=True,
            )

    # ---------- búsqueda ----------

    def _buscar(self):
        texto = self.search_input.text().strip()
        if not texto:
            return
        if not self.client.conectado:
            self._pedir_cuenta_y_conectar()
            return
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        self._set_status(f"Buscando «{texto}»…", loading=True)
        self._search_worker = _SearchWorker(self.client, texto, self)
        self._search_worker.done.connect(self._on_resultados)
        self._search_worker.start()

    def _on_resultados(self, resultados):
        self._set_status(f"{len(resultados)} resultados." if resultados else "Sin resultados.")
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(False)
        self.select_all_check.blockSignals(False)
        self.results_list.clear()
        for r in sorted(resultados, key=lambda x: -x["upload_speed"])[:200]:
            self._agregar_fila_resultado(r)

    def _agregar_fila_resultado(self, r: dict):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 6, 10, 6)
        row_layout.setSpacing(10)

        checkbox = QCheckBox()
        checkbox.setFixedWidth(20)
        row.checkbox = checkbox
        row_layout.addWidget(checkbox)

        text_col = QVBoxLayout()
        nombre = r["filename"].rsplit("\\", 1)[-1]
        name_label = QLabel(nombre)
        name_label.setObjectName("mediaRowTitle")
        name_label.setWordWrap(True)
        text_col.addWidget(name_label)

        detalle = f"{r['username']} · {_formatear_tamano(r['size'])}"
        if r.get("bitrate"):
            detalle += f" · {r['bitrate']} kbps"
        detalle += f" · {_formatear_velocidad(r['upload_speed'])}"
        if r.get("queue_length"):
            detalle += f" · {r['queue_length']} en cola"
        detail_label = QLabel(detalle)
        detail_label.setObjectName("mediaRowDetail")
        detail_label.setWordWrap(True)
        text_col.addWidget(detail_label)

        row_layout.addLayout(text_col, stretch=1)

        download_btn = QPushButton("Descargar")
        download_btn.setFixedWidth(90)
        set_variant(download_btn, "secondary")
        download_btn.clicked.connect(lambda: self._descargar(r))
        row_layout.addWidget(download_btn)

        item = QListWidgetItem()
        item.setData(ROLE_RESULT, r)
        item.setSizeHint(row.sizeHint())
        self.results_list.addItem(item)
        self.results_list.setItemWidget(item, row)

    def _descargar(self, r: dict):
        error = self.client.descargar(r["username"], r["filename"], r["size"])
        if error:
            QMessageBox.warning(self, "No se pudo descargar", error)
            return
        self._refrescar_descargas()

    def _marcar_todos(self, marcado: bool):
        for i in range(self.results_list.count()):
            row = self.results_list.itemWidget(self.results_list.item(i))
            if row is not None:
                row.checkbox.setChecked(marcado)

    def _descargar_seleccionados(self):
        seleccionados = []
        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            row = self.results_list.itemWidget(item)
            if row is not None and row.checkbox.isChecked():
                seleccionados.append(item.data(ROLE_RESULT))
        if not seleccionados:
            QMessageBox.information(self, "Nada seleccionado", "Marca al menos un resultado para descargar.")
            return
        errores = 0
        for r in seleccionados:
            if self.client.descargar(r["username"], r["filename"], r["size"]):
                errores += 1
        self._refrescar_descargas()
        if errores:
            QMessageBox.warning(
                self, "Algunas descargas fallaron",
                f"No se pudieron encolar {errores} de {len(seleccionados)} descargas.",
            )

    # ---------- descargas activas ----------

    def _refrescar_descargas(self):
        if not self.client.conectado:
            return
        descargas = self.client.listar_descargas()
        self.downloads_list.clear()
        for d in descargas:
            self._agregar_fila_descarga(d)
        self._actualizar_resumen_descargas(descargas)

    def _actualizar_resumen_descargas(self, descargas: list):
        if not descargas:
            self.downloads_summary_label.setText("")
            self.cancel_all_btn.setEnabled(False)
            self.clear_completed_btn.setEnabled(False)
            return
        completadas = sum(1 for d in descargas if "Completed" in d["state"])
        activas = sum(1 for d in descargas if _esta_activa(d))
        con_error = len(descargas) - completadas - activas
        self.cancel_all_btn.setEnabled(bool(activas))
        self.clear_completed_btn.setEnabled(bool(completadas + con_error))
        promedio = sum(d["percent_complete"] for d in descargas) / len(descargas)
        partes = []
        if activas:
            partes.append(f"{activas} activa{'s' if activas != 1 else ''}")
        if completadas:
            partes.append(f"{completadas} completada{'s' if completadas != 1 else ''}")
        if con_error:
            partes.append(f"{con_error} con error")
        self.downloads_summary_label.setText(f"{' · '.join(partes)} · {promedio:.0f}% de media")

    def _agregar_fila_descarga(self, d: dict):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        # Filas algo más compactas que antes (6px -> 4px de margen vertical,
        # +1px de separación entre líneas) para que quepan más descargas
        # visibles de golpe -- con listas de decenas de descargas activas
        # a la vez, cada fila de más pesa.
        row_layout.setContentsMargins(10, 4, 10, 4)
        row_layout.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        nombre = d["filename"].rsplit("\\", 1)[-1]
        name_label = QLabel(f"{nombre}  ({d['username']})")
        name_label.setObjectName("mediaRowTitle")
        name_label.setWordWrap(True)
        text_col.addWidget(name_label)

        progress = QProgressBar()
        progress.setObjectName("mediaProgress")
        progress.setRange(0, 100)
        progress.setValue(int(d["percent_complete"]))
        progress.setTextVisible(False)
        progress.setFixedHeight(8)
        text_col.addWidget(progress)

        estado_txt = d["state"]
        if "Completed" in estado_txt:
            detalle = "Completado"
        elif "Errored" in estado_txt or "Cancelled" in estado_txt or "Rejected" in estado_txt:
            detalle = "Error"
        else:
            detalle = f"{d['percent_complete']:.0f}% · {_formatear_velocidad(d['average_speed'])}"
        detail_label = QLabel(detalle)
        detail_label.setObjectName("mediaRowDetail")
        detail_label.setWordWrap(True)
        text_col.addWidget(detail_label)

        row_layout.addLayout(text_col, stretch=1)

        abrir_btn = QPushButton("Abrir")
        abrir_btn.setFixedWidth(60)
        set_variant(abrir_btn, "secondary")
        abrir_btn.setToolTip("Ver en la carpeta del explorador")
        abrir_btn.clicked.connect(lambda: self._abrir_descarga(d["filename"]))
        row_layout.addWidget(abrir_btn)

        if _esta_activa(d):
            cancelar_btn = QPushButton("Cancelar")
            cancelar_btn.setFixedWidth(85)
            set_variant(cancelar_btn, "secondary")
            cancelar_btn.clicked.connect(lambda: self._cancelar_descarga(d["username"], d["id"]))
            row_layout.addWidget(cancelar_btn)

        item = QListWidgetItem()
        item.setData(ROLE_DOWNLOAD_ID, (d["username"], d["id"]))
        item.setSizeHint(row.sizeHint())
        self.downloads_list.addItem(item)
        self.downloads_list.setItemWidget(item, row)

    def _cancelar_descarga(self, username: str, id_: str):
        """Slot del botón "Cancelar" de una fila. NO hace el trabajo aquí:
        ese botón vive dentro del widget de fila que downloads_list posee, y
        cancelar acaba llamando a _refrescar_descargas() -> clear(), que
        destruye la fila entera... incluido el botón que en ese momento
        sigue emitiendo esta misma señal. Al volver el slot, Qt regresa a un
        objeto C++ ya liberado y el proceso muere de golpe, sin traceback.
        Con singleShot(0) el trabajo corre en la siguiente vuelta del bucle
        de eventos, cuando Qt ya ha salido del botón y destruirlo es seguro."""
        QTimer.singleShot(0, lambda: self._cancelar_descarga_ahora(username, id_))

    def _cancelar_descarga_ahora(self, username: str, id_: str):
        # cancelar_descarga() ya cancela Y elimina esta transferencia
        # concreta en la propia llamada (?remove=true, ver su docstring en
        # core/soulseek_client.py) -- así la fila desaparece de la lista
        # en un solo paso sin arrastrar de paso otras descargas ya
        # completadas o con error que el usuario no ha tocado.
        try:
            self.client.cancelar_descarga(username, id_)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo cancelar", str(exc))
            return
        self._refrescar_descargas()

    def _cancelar_todas(self):
        """Cancela de golpe todas las descargas que sigan vivas. Se pide la
        lista de nuevo al cliente en vez de leer la de la interfaz: el timer
        de refresco corre cada 2s, así que lo pintado puede estar desfasado
        y se intentaría cancelar algo que ya terminó."""
        if not self.client.conectado:
            return
        try:
            activas = [d for d in self.client.listar_descargas() if _esta_activa(d)]
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo cancelar", str(exc))
            return
        if not activas:
            QMessageBox.information(
                self, "Nada que cancelar", "No hay descargas en curso ahora mismo."
            )
            return

        respuesta = QMessageBox.question(
            self, "Cancelar todas las descargas",
            f"¿Cancelar las {len(activas)} descargas en curso?\n\n"
            "Las que ya se hayan completado no se tocan.",
        )
        if respuesta != QMessageBox.Yes:
            return

        # cancelar_descarga() ya elimina cada transferencia además de
        # cancelarla (ver su docstring) -- las completadas/con error de
        # antes no se tocan, tal cual promete el diálogo de arriba.
        errores = 0
        for d in activas:
            try:
                self.client.cancelar_descarga(d["username"], d["id"])
            except Exception:
                errores += 1
        self._refrescar_descargas()
        if errores:
            QMessageBox.warning(
                self, "Algunas no se pudieron cancelar",
                f"No se pudieron cancelar {errores} de {len(activas)} descargas.",
            )

    def _borrar_completadas(self):
        """Limpia del lado de slskd las descargas que ya no están activas
        (completadas, canceladas, con error) -- sin esto se acumulan para
        siempre y cada refresco de la lista (cada 2s) va reconstruyendo cada
        vez más filas, notándose como lentitud creciente cuanto más se
        descarga en la sesión."""
        if not self.client.conectado:
            return
        try:
            self.client.limpiar_completadas()
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo limpiar", str(exc))
            return
        self._refrescar_descargas()

    def _abrir_descarga(self, remote_filename: str):
        """Intenta seleccionar el archivo descargado en el explorador. slskd
        recrea, dentro de dest_dir, la estructura de carpetas remota menos su
        primer segmento (comprobado con una descarga real) -- si el archivo
        adivinado no existe (todavía descargando, o estructura distinta),
        se abre directamente la carpeta de descargas como alternativa segura."""
        partes = remote_filename.replace("/", "\\").split("\\")
        subruta = partes[1:] if len(partes) > 1 else partes
        ruta = os.path.join(self.dest_dir, *subruta)
        if os.path.isfile(ruta):
            if os.name == "nt":
                try:
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(ruta)}"')
                    return
                except OSError:
                    pass
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(ruta)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.dest_dir))

    # ---------- carpeta destino ----------

    def set_dest_dir(self, path: str):
        self.dest_dir = path

    # ---------- cierre ----------

    def shutdown(self, on_wait=None):
        self._poll_timer.stop()
        self._login_timer.stop()
        # cerrar() primero: marca al cliente como cerrándose, lo que hace
        # que conectar() (si _ensure_worker sigue dentro de él) aborte en
        # su próximo punto de comprobación en vez de seguir buscando
        # puerto libre -- así el wait() de abajo ya no compite contra una
        # conexión en marcha que puede tardar mucho más que 1s.
        self.client.cerrar(on_wait=on_wait)
        if self._ensure_worker is not None and self._ensure_worker.isRunning():
            self._ensure_worker.wait(1000)
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_worker.wait(1000)

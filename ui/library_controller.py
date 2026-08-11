"""
Controlador de la biblioteca personal de TDT & Radio VIP: añadir, editar y
eliminar canales/emisoras propios, importar listas M3U completas, y
exportar/importar la copia de seguridad de todos los datos del usuario.

Extraído de ui/main_window.py por el mismo motivo que el resto de
controladores (ver ui/playback_controller.py) — toda esta lógica
manipula tv_channels_data/radio_stations_data y los archivos JSON de
core/channels.py, core/radio.py y core/backup.py, sin relación directa
con cómo se construye o pinta la ventana.

Coder By X@R
"""
import json
from pathlib import Path

import requests
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from core import backup as backup_module
from core import channels as tv_channels
from core import favorites as fav_store
from core import radio as radio_stations
from ui.dialogs import AddEntryDialog, ImportPlaylistDialog, ManageChannelsDialog
from ui.fetch_worker import FetchWorker
from ui.toast import show_toast


class LibraryController:
    """Alta/edición/borrado de canales propios, import M3U y copias de seguridad."""

    def __init__(self, window):
        self.win = window

    # ---------- Añadir / editar / eliminar manual ----------

    def open_add_entry_dialog(self):
        win = self.win
        dialog = AddEntryDialog(win)
        if dialog.exec() != QDialog.Accepted or not dialog.result_data:
            return
        data = dialog.result_data
        group = data["group"] or "Personalizados"

        if data["type"] == "tv":
            channel = tv_channels.Channel(name=data["name"], url=data["url"], logo=data["logo"], group=group)
            tv_channels.add_custom_channel(channel)
            win.tv_channels_data.append(channel)
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            station = radio_stations.Station(
                name=data["name"], url=data["url"], favicon=data["logo"], tags=group
            )
            radio_stations.add_custom_station(station)
            win.radio_stations_data.append(station)
            win.lists.populate_radio_list(win.radio_stations_data)

        win.statusBar().showMessage(f"«{data['name']}» añadido a tu lista.", 5000)

    def edit_custom_entry(self, data: dict):
        win = self.win
        dialog = AddEntryDialog(win, initial=data)
        if dialog.exec() != QDialog.Accepted or not dialog.result_data:
            return
        new_data = dialog.result_data
        group = new_data["group"] or "Personalizados"
        old_name = data["name"]

        if new_data["type"] == "tv":
            channel = tv_channels.Channel(
                name=new_data["name"], url=new_data["url"], logo=new_data["logo"], group=group
            )
            tv_channels.update_custom_channel(old_name, channel)
            win.tv_channels_data = [channel if c.name == old_name else c for c in win.tv_channels_data]
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            station = radio_stations.Station(
                name=new_data["name"], url=new_data["url"], favicon=new_data["logo"], tags=group
            )
            radio_stations.update_custom_station(old_name, station)
            win.radio_stations_data = [station if s.name == old_name else s for s in win.radio_stations_data]
            win.lists.populate_radio_list(win.radio_stations_data)

        if fav_store.is_favorite(win.favorites, data["type"], old_name):
            win.favorites = fav_store.toggle_favorite(data["type"], old_name, data.get("url", ""))
            win.favorites = fav_store.toggle_favorite(
                new_data["type"], new_data["name"], new_data["url"], new_data["logo"]
            )
        win.lists.refresh_favorites_tab()
        win.lists.refresh_history_tab()

        if win.current_type == data["type"] and win.current_name == old_name:
            win.current_name = new_data["name"]
            win.current_url = new_data["url"]
            icon = "TV" if data["type"] == "tv" else "FM"
            win.now_title.setText(f"{icon} · {new_data['name']}")

        win.statusBar().showMessage(f"«{new_data['name']}» actualizado.", 4000)

    def delete_custom_entry(self, data: dict):
        """
        Elimina de inmediato (sin diálogo de confirmación bloqueante) y
        muestra un aviso con "Deshacer" unos segundos -- se guarda una
        copia de lo borrado (canal/emisora + si era favorito) para poder
        restaurarlo tal cual si el usuario pulsa deshacer a tiempo.
        """
        win = self.win
        item_type, name = data["type"], data["name"]
        was_favorite = fav_store.is_favorite(win.favorites, item_type, name)

        if item_type == "tv":
            snapshot = next((c for c in win.tv_channels_data if c.name == name), None)
            tv_channels.remove_custom_channel(name)
            win.tv_channels_data = [c for c in win.tv_channels_data if c.name != name]
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            snapshot = next((s for s in win.radio_stations_data if s.name == name), None)
            radio_stations.remove_custom_station(name)
            win.radio_stations_data = [s for s in win.radio_stations_data if s.name != name]
            win.lists.populate_radio_list(win.radio_stations_data)

        if was_favorite:
            win.favorites = fav_store.toggle_favorite(item_type, name, data.get("url", ""))
            win.lists.refresh_favorites_tab()

        if win.current_type == item_type and win.current_name == name:
            win.playback.stop_playback()

        def _deshacer():
            self._restore_deleted_entry(item_type, snapshot, was_favorite)

        show_toast(
            win, f"«{name}» eliminado.",
            undo_text="Deshacer", on_undo=(_deshacer if snapshot is not None else None),
        )

    def _restore_deleted_entry(self, item_type: str, snapshot, was_favorite: bool):
        win = self.win
        if snapshot is None:
            return
        if item_type == "tv":
            tv_channels.add_custom_channel(snapshot)
            win.tv_channels_data.append(snapshot)
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
            logo = snapshot.logo
        else:
            radio_stations.add_custom_station(snapshot)
            win.radio_stations_data.append(snapshot)
            win.lists.populate_radio_list(win.radio_stations_data)
            logo = snapshot.favicon

        if was_favorite:
            win.favorites = fav_store.toggle_favorite(item_type, snapshot.name, snapshot.url, logo)
            win.lists.refresh_favorites_tab()

        win.statusBar().showMessage(f"«{snapshot.name}» restaurado.", 4000)

    # ---------- Gestión múltiple (borrado por lotes) ----------

    def open_manage_channels_dialog(self, entry_type: str = "tv"):
        """
        Abre el gestor de canales/emisoras en sus tres ámbitos: borrar
        personalizados de golpe (pensado sobre todo para limpiar después de
        importar una lista M3U grande), ocultar canales de la lista pública
        que no interesen, o restaurar los ocultados antes (ver
        ManageChannelsDialog).

        "public" se calcula restando los personalizados de la lista ya
        combinada en memoria (win.tv_channels_data/radio_stations_data),
        que ya viene sin los ocultos (filter_hidden se aplica al cargar) --
        así el diálogo nunca lista el mismo nombre en dos ámbitos a la vez.
        """
        win = self.win
        custom_tv = tv_channels.load_custom_channels()
        custom_tv_names = {c.name for c in custom_tv}
        custom_radio = radio_stations.load_custom_stations()
        custom_radio_names = {s.name for s in custom_radio}

        dialog = ManageChannelsDialog(
            tv_datos={
                "custom": custom_tv,
                "public": [c for c in win.tv_channels_data if c.name not in custom_tv_names],
                "hidden_names": tv_channels.load_hidden_channel_names(),
            },
            radio_datos={
                "custom": custom_radio,
                "public": [s for s in win.radio_stations_data if s.name not in custom_radio_names],
                "hidden_names": radio_stations.load_hidden_station_names(),
            },
            on_delete=self._delete_custom_entries,
            on_hide=self.hide_entries,
            on_unhide=self.unhide_entries,
            entry_type=entry_type,
            parent=win,
        )
        dialog.exec()

    def _delete_custom_entries(self, entry_type: str, names: list) -> int:
        """
        Borrado por lotes: mismo efecto neto que llamar a
        delete_custom_entry() una vez por nombre (quita del almacén
        personalizado, de la lista en memoria, de favoritos si estaban
        marcados, y refresca la lista visual), pero con una sola
        lectura+escritura del JSON (remove_custom_channels/_stations) en
        vez de una por elemento, y sin el toast de "deshacer" individual --
        no tiene sentido para una selección de varios a la vez.
        """
        win = self.win
        nombres = set(names)
        if not nombres:
            return 0

        if entry_type == "tv":
            borrados = tv_channels.remove_custom_channels(nombres)
            win.tv_channels_data = [c for c in win.tv_channels_data if c.name not in nombres]
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            borrados = radio_stations.remove_custom_stations(nombres)
            win.radio_stations_data = [s for s in win.radio_stations_data if s.name not in nombres]
            win.lists.populate_radio_list(win.radio_stations_data)

        tocó_favoritos = False
        for nombre in nombres:
            if fav_store.is_favorite(win.favorites, entry_type, nombre):
                win.favorites = fav_store.toggle_favorite(entry_type, nombre, "")
                tocó_favoritos = True
        if tocó_favoritos:
            win.lists.refresh_favorites_tab()

        if win.current_type == entry_type and win.current_name in nombres:
            win.playback.stop_playback()

        win.statusBar().showMessage(f"Se eliminaron {borrados} elemento(s).", 5000)
        return borrados

    def hide_entries(self, entry_type: str, names: list) -> int:
        """
        Oculta canales/emisoras de la lista PÚBLICA (iptv-org/Radio-Browser)
        sin tocar lo que se descarga -- ver core.channels.hide_channels /
        core.radio.hide_stations. Se quitan también de la lista en memoria
        y de favoritos si estaban marcados: no tiene sentido dejar en
        favoritos algo que ya no aparece en ninguna lista (mismo criterio
        que _delete_custom_entries).

        Público (sin guion bajo) a propósito: además de ManageChannelsDialog
        (on_hide), lo llama PlaybackController cuando se acepta el aviso de
        "canal caído repetidamente" (ver _maybe_offer_autohide).
        """
        win = self.win
        nombres = set(names)
        if not nombres:
            return 0

        if entry_type == "tv":
            ocultados = tv_channels.hide_channels(nombres)
            win.tv_channels_data = [c for c in win.tv_channels_data if c.name not in nombres]
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            ocultados = radio_stations.hide_stations(nombres)
            win.radio_stations_data = [s for s in win.radio_stations_data if s.name not in nombres]
            win.lists.populate_radio_list(win.radio_stations_data)

        tocó_favoritos = False
        for nombre in nombres:
            if fav_store.is_favorite(win.favorites, entry_type, nombre):
                win.favorites = fav_store.toggle_favorite(entry_type, nombre, "")
                tocó_favoritos = True
        if tocó_favoritos:
            win.lists.refresh_favorites_tab()

        if win.current_type == entry_type and win.current_name in nombres:
            win.playback.stop_playback()

        win.statusBar().showMessage(f"Se ocultaron {ocultados} elemento(s) de la lista pública.", 5000)
        return ocultados

    def unhide_entries(self, entry_type: str, names: list) -> int:
        """
        Restaura canales/emisoras ocultos antes. Sus datos completos (url,
        logo...) ya no están en memoria -- se filtraron al cargar -- así
        que la forma fiable de que reaparezcan es recargar desde caché
        (force=False, no hace falta red) en vez de reconstruirlos a mano.
        """
        win = self.win
        nombres = set(names)
        if not nombres:
            return 0

        if entry_type == "tv":
            restaurados = tv_channels.unhide_channels(nombres)
            win._load_tv_channels()
        else:
            restaurados = radio_stations.unhide_stations(nombres)
            win._load_radio_stations()

        win.statusBar().showMessage(f"Se restauraron {restaurados} elemento(s).", 5000)
        return restaurados

    # ---------- Importar lista M3U ----------

    def open_import_playlist_dialog(self):
        win = self.win
        dialog = ImportPlaylistDialog(win)
        if dialog.exec() != QDialog.Accepted:
            return
        entry_type, source = dialog.get_values()
        if not source:
            return

        win.statusBar().showMessage("Importando lista…")
        worker = FetchWorker(self._fetch_and_parse_playlist, source)
        worker.done.connect(lambda parsed: self._on_playlist_fetched(parsed, entry_type))
        win._import_worker = worker
        worker.start()

    @staticmethod
    def _fetch_and_parse_playlist(source: str):
        """
        Descarga/lee Y parsea la lista, todo dentro del hilo de fondo de
        FetchWorker. Antes solo se descargaba aquí y parse_m3u() se llamaba
        ya en el hilo principal, dentro de _on_playlist_fetched() -- con
        listas de varios miles de canales, ese parseo (aunque más rápido
        que poblar la lista visual) también se notaba como congelación.
        parse_m3u() es una función pura sin nada de Qt, así que no hay
        problema en llamarla desde este hilo.
        """
        try:
            if source.lower().startswith(("http://", "https://")):
                resp = requests.get(source, timeout=15)
                resp.raise_for_status()
                text = resp.text
            else:
                text = Path(source).read_text(encoding="utf-8", errors="ignore")
        except (requests.RequestException, OSError):
            return None
        return tv_channels.parse_m3u(text)

    def _on_playlist_fetched(self, parsed, entry_type: str):
        win = self.win
        if getattr(win, "_is_closing", False):
            return
        if parsed is None:
            QMessageBox.warning(
                win, "No se pudo importar",
                "No se pudo leer la lista. Revisa la URL o la ruta del archivo e inténtalo de nuevo."
            )
            return

        if not parsed:
            QMessageBox.warning(
                win, "Lista vacía",
                "No se encontraron canales en formato M3U válido en ese origen."
            )
            return

        existing_names = {
            c.name for c in (win.tv_channels_data if entry_type == "tv" else [])
        } | {
            s.name for s in (win.radio_stations_data if entry_type == "radio" else [])
        }

        added = 0
        if entry_type == "tv":
            # Se acumulan en memoria y se guardan de una sola vez al final
            # (add_custom_channels) en vez de leer y reescribir el JSON
            # entero por cada canal — con listas de cientos/miles de
            # canales, la diferencia es notable y evita congelar la UI.
            nuevos = []
            for ch in parsed:
                if ch.name in existing_names:
                    continue
                nuevos.append(ch)
                existing_names.add(ch.name)
            tv_channels.add_custom_channels(nuevos)
            win.tv_channels_data.extend(nuevos)
            added = len(nuevos)
            win.lists.refresh_group_filter()
            win.lists.populate_tv_list(win.tv_channels_data)
        else:
            nuevas = []
            for ch in parsed:
                if ch.name in existing_names:
                    continue
                nuevas.append(radio_stations.Station(name=ch.name, url=ch.url, favicon=ch.logo, tags=ch.group))
                existing_names.add(ch.name)
            radio_stations.add_custom_stations(nuevas)
            win.radio_stations_data.extend(nuevas)
            added = len(nuevas)
            win.lists.populate_radio_list(win.radio_stations_data)

        win.statusBar().showMessage(f"Se importaron {added} elementos nuevos.", 6000)
        QMessageBox.information(
            win, "Importación completada",
            f"Se han encontrado {len(parsed)} canales en la lista y se han añadido {added} nuevos "
            f"({len(parsed) - added} ya estaban en tu lista)."
        )

    # ---------- Copia de seguridad ----------

    def export_backup(self):
        win = self.win
        destino, _ = QFileDialog.getSaveFileName(
            win, "Exportar copia de seguridad",
            backup_module.sugerir_nombre_backup(),
            "Copia de seguridad (*.json)",
        )
        if not destino:
            return
        try:
            backup_module.export_backup(destino)
        except OSError as exc:
            QMessageBox.warning(win, "No se pudo exportar", str(exc))
            return
        QMessageBox.information(
            win, "Copia de seguridad exportada",
            f"Favoritos, historial, ajustes y canales personalizados guardados en:\n{destino}"
        )

    def import_backup(self):
        win = self.win
        origen, _ = QFileDialog.getOpenFileName(
            win, "Importar copia de seguridad", "",
            "Copia de seguridad (*.json)",
        )
        if not origen:
            return
        respuesta = QMessageBox.question(
            win, "Importar copia de seguridad",
            "Esto sobrescribirá tus favoritos, historial, ajustes y canales "
            "personalizados actuales con los del archivo elegido.\n\n"
            "¿Continuar?",
        )
        if respuesta != QMessageBox.Yes:
            return
        try:
            restaurado = backup_module.import_backup(origen)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(win, "No se pudo importar", str(exc))
            return
        QMessageBox.information(
            win, "Copia de seguridad importada",
            f"Restaurado: {', '.join(restaurado) if restaurado else '(nada — el archivo estaba vacío)'}"
            "\n\nCierra y vuelve a abrir la aplicación para que se aplique del todo."
        )

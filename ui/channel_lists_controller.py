"""
Controlador de listas de TDT & Radio VIP: poblar y refrescar las listas de
TV, radio, favoritos e historial, el filtro de categoría/carpeta y la
búsqueda por texto.

Extraído de ui/main_window.py por el mismo motivo que
ui.playback_controller.PlaybackController y ui.window_chrome.WindowChrome —
ver el docstring de PlaybackController para la explicación completa del
porqué del patrón (estado en MainWindow, comportamiento aquí). Antes esta
lógica de "pintar filas en las listas" vivía mezclada, en la misma clase,
con la reproducción, el cromado de ventana y el resto de secciones.

Coder By X@R
"""
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from core import channels as tv_channels
from core import epg as epg_module
from core import favorites as fav_store
from core import radio as radio_stations
from ui.widgets import ROLE_CUSTOM, ROLE_DATA, ROLE_FAV, ROLE_LOGO, ROLE_PLAYING, ChannelDelegate

# Por encima de esto, se omite la descarga de logos al poblar la lista (se
# ve el icono genérico de TV/radio en su lugar -- ChannelDelegate ya sabe
# dibujarlo, ver ui/widgets.py). Una lista de un país normal tiene como
# mucho unos pocos cientos de canales y nunca se acerca a este límite, pero
# importar el índice MUNDIAL de iptv-org (index.m3u, varios miles de
# canales) disparaba un LogoLoader.load() -- y por tanto una petición de
# red -- por cada uno de golpe: miles de peticiones HTTP/2 concurrentes al
# mismo servidor de logos, que el servidor acababa rechazando en masa
# ("Server refused a stream" / "HTTP/2 protocol error" a decenas por
# segundo) y que dejaba la aplicación entera sin responder mientras tanto
# -- no solo la lista, cualquier otra ventana o diálogo también, porque el
# hilo de la interfaz estaba desbordado de señales de red pendientes.
_MAX_CHANNELS_CON_LOGOS = 600


class ChannelListsController:
    """Poblado, refresco, filtro y búsqueda de las listas de canales."""

    def __init__(self, window):
        self.win = window

    # ---------- Logos ----------

    def request_logo(self, url: str, item: QListWidgetItem, list_widget: QListWidget):
        if not url:
            return

        def _on_ready(pixmap):
            item.setData(ROLE_LOGO, pixmap)
            list_widget.viewport().update()

        self.win.logo_loader.load(url, _on_ready, size=ChannelDelegate.LOGO_SIZE)

    def _epg_now_text(self, tvg_id: str) -> str:
        """
        "Ahora: <programa>" para el mini-EPG de cada fila de la lista de TV,
        o "" si no hay guía cargada todavía, el canal no trae tvg_id, o no
        hay programación en curso para él en este momento. Usa la guía ya
        en memoria (win.epg_guide) -- sin red aquí, esa la hace
        EpgController.load() aparte.
        """
        win = self.win
        if not win.epg_guide or not tvg_id:
            return ""
        current, _ = epg_module.get_now_next(win.epg_guide, tvg_id)
        return f"Ahora: {current.title}" if current else ""

    # ---------- Poblado de listas ----------

    def populate_tv_list(self, channels_list):
        win = self.win
        custom_names = {c.name for c in tv_channels.load_custom_channels()}
        cargar_logos = len(channels_list) <= _MAX_CHANNELS_CON_LOGOS
        # setUpdatesEnabled(False): con listas grandes (importar un M3U de
        # varios miles de canales, o simplemente un país con muchos canales)
        # cada addItem() por separado repintaba y recalculaba el layout de
        # la lista una a una -- con miles de canales eso es lo que se veía
        # como "se pone lento y se cuelga la app" (reportado). Cortando los
        # repintados hasta que la lista entera está poblada, Qt hace un
        # único repintado al final en vez de miles.
        win.tv_list.setUpdatesEnabled(False)
        try:
            win.tv_list.clear()
            for ch in channels_list:
                item = QListWidgetItem()
                # Subtítulo combinado: categoría + mini-EPG ("Ahora: ...")
                # cuando hay guía cargada, uno solo de los dos si falta el
                # otro (ver ChannelDelegate.paint, que ahora prioriza
                # "subtitle" sobre "group" para decidir qué texto pintar --
                # el punto de color de la categoría se sigue dibujando por
                # separado a partir de "group", no cambia).
                epg_now = self._epg_now_text(ch.tvg_id)
                if ch.group and epg_now:
                    subtitle = f"{ch.group} · {epg_now}"
                else:
                    subtitle = epg_now or ch.group
                item.setData(ROLE_DATA, {
                    "type": "tv", "name": ch.name, "url": ch.url,
                    "logo": ch.logo, "tvg_id": ch.tvg_id, "group": ch.group,
                    "subtitle": subtitle,
                })
                item.setData(ROLE_FAV, fav_store.is_favorite(win.favorites, "tv", ch.name))
                item.setData(ROLE_PLAYING, win.current_type == "tv" and win.current_name == ch.name)
                item.setData(ROLE_CUSTOM, ch.name in custom_names)
                win.tv_list.addItem(item)
                if cargar_logos:
                    self.request_logo(ch.logo, item, win.tv_list)
        finally:
            win.tv_list.setUpdatesEnabled(True)
        if not cargar_logos:
            win.statusBar().showMessage(
                f"Lista de {len(channels_list)} canales: se omiten los logos "
                "para no saturar la red (se ven con icono genérico).", 8000
            )

    def populate_radio_list(self, stations_list):
        win = self.win
        custom_names = {s.name for s in radio_stations.load_custom_stations()}
        cargar_logos = len(stations_list) <= _MAX_CHANNELS_CON_LOGOS
        win.radio_list.setUpdatesEnabled(False)  # ver comentario en populate_tv_list
        try:
            win.radio_list.clear()
            for st in stations_list:
                item = QListWidgetItem()
                subtitle = f"{st.bitrate} kbps" if st.bitrate else (st.tags or "")
                item.setData(ROLE_DATA, {
                    "type": "radio", "name": st.name, "url": st.url,
                    "logo": st.favicon, "subtitle": subtitle,
                })
                item.setData(ROLE_FAV, fav_store.is_favorite(win.favorites, "radio", st.name))
                item.setData(ROLE_PLAYING, win.current_type == "radio" and win.current_name == st.name)
                item.setData(ROLE_CUSTOM, st.name in custom_names)
                win.radio_list.addItem(item)
                if cargar_logos:
                    self.request_logo(st.favicon, item, win.radio_list)
        finally:
            win.radio_list.setUpdatesEnabled(True)
        if not cargar_logos:
            win.statusBar().showMessage(
                f"Lista de {len(stations_list)} emisoras: se omiten los logos "
                "para no saturar la red (se ven con icono genérico).", 8000
            )

    def refresh_favorites_tab(self):
        win = self.win
        win.fav_list.clear()
        custom_tv = {c.name for c in tv_channels.load_custom_channels()}
        custom_radio = {s.name for s in radio_stations.load_custom_stations()}
        for fav in win.favorites:
            item = QListWidgetItem()
            data = dict(fav)
            # Reutiliza el mismo mecanismo visual de "categoría" que ya
            # tienen las tarjetas de TV (punto de color + texto) para
            # mostrar la carpeta del favorito, en vez de inventar un
            # indicador nuevo.
            data["group"] = fav.get("folder", "")
            item.setData(ROLE_DATA, data)
            item.setData(ROLE_FAV, True)
            item.setData(ROLE_PLAYING, win.current_type == fav["type"] and win.current_name == fav["name"])
            is_custom = fav["name"] in (custom_tv if fav["type"] == "tv" else custom_radio)
            item.setData(ROLE_CUSTOM, is_custom)
            win.fav_list.addItem(item)
            self.request_logo(fav.get("logo", ""), item, win.fav_list)

        sidebar = getattr(win, "library_sidebar", None)
        if sidebar is not None:
            sidebar.refresh()

    def refresh_history_tab(self):
        win = self.win
        win.hist_list.clear()
        custom_tv = {c.name for c in tv_channels.load_custom_channels()}
        custom_radio = {s.name for s in radio_stations.load_custom_stations()}
        for entry in win.history:
            item = QListWidgetItem()
            data = dict(entry)
            data["subtitle"] = entry.get("timestamp", "")
            item.setData(ROLE_DATA, data)
            item.setData(ROLE_FAV, fav_store.is_favorite(win.favorites, entry["type"], entry["name"]))
            item.setData(ROLE_PLAYING, win.current_type == entry["type"] and win.current_name == entry["name"])
            is_custom = entry["name"] in (custom_tv if entry["type"] == "tv" else custom_radio)
            item.setData(ROLE_CUSTOM, is_custom)
            win.hist_list.addItem(item)

        sidebar = getattr(win, "library_sidebar", None)
        if sidebar is not None:
            sidebar.refresh()

    def persist_favorites_order(self):
        """
        Llamado tras arrastrar una fila en la pestaña de Favoritos
        (QListWidget.InternalMove, ver ui/main_window._make_list). Relee el
        orden visual actual de win.fav_list y lo guarda como el nuevo orden
        de win.favorites -- así el arrastre sobrevive a cerrar y reabrir la
        app, no es solo un reordenado visual de la sesión actual.
        """
        win = self.win
        vistos = set()
        nuevo_orden = []
        for i in range(win.fav_list.count()):
            data = win.fav_list.item(i).data(ROLE_DATA) or {}
            clave = (data.get("type"), data.get("name"))
            original = next(
                (f for f in win.favorites if (f.get("type"), f.get("name")) == clave), None
            )
            if original is not None and clave not in vistos:
                nuevo_orden.append(original)
                vistos.add(clave)
        # Red de seguridad: cualquier favorito que por lo que sea no haya
        # aparecido en la lista visual (no debería pasar) se añade al
        # final en vez de perderse silenciosamente.
        for f in win.favorites:
            clave = (f.get("type"), f.get("name"))
            if clave not in vistos:
                nuevo_orden.append(f)
                vistos.add(clave)

        win.favorites = fav_store.reorder(nuevo_orden)

    def mark_playing_everywhere(self):
        win = self.win
        # home_recent_carousel / home_recommended_carousel no entran en este
        # bucle: son CarouselCard (ui/carousel.py), no QListWidgetItem con
        # ROLE_PLAYING -- no llevan indicador de "sonando ahora" propio, se
        # limitan a repoblarse cada vez que se entra en Inicio.
        for lst in (win.tv_list, win.radio_list, win.fav_list, win.hist_list, win.home_fav_list):
            for i in range(lst.count()):
                item = lst.item(i)
                data = item.data(ROLE_DATA) or {}
                is_current = data.get("type") == win.current_type and data.get("name") == win.current_name
                item.setData(ROLE_PLAYING, is_current and not win._playback_failed)
            lst.viewport().update()

    def mark_favorites_everywhere(self):
        win = self.win
        for lst in (win.tv_list, win.radio_list, win.hist_list):
            for i in range(lst.count()):
                item = lst.item(i)
                data = item.data(ROLE_DATA) or {}
                item.setData(ROLE_FAV, fav_store.is_favorite(win.favorites, data.get("type"), data.get("name")))
            lst.viewport().update()

    # ---------- Filtros de categoría / carpeta ----------

    def refresh_folder_filter(self):
        win = self.win
        carpetas = fav_store.get_folders(win.favorites)
        current = win.group_filter.currentText()
        win.group_filter.blockSignals(True)
        win.group_filter.clear()
        win.group_filter.addItem("Todas las carpetas")
        if carpetas:
            win.group_filter.addItem("Sin carpeta")
            win.group_filter.addItems(carpetas)
        idx = win.group_filter.findText(current)
        win.group_filter.setCurrentIndex(idx if idx >= 0 else 0)
        win.group_filter.blockSignals(False)

    def refresh_group_filter(self):
        win = self.win
        groups = sorted({c.group for c in win.tv_channels_data if c.group})
        current = win.group_filter.currentText()
        win.group_filter.blockSignals(True)
        win.group_filter.clear()
        win.group_filter.addItem("Todas las categorías")
        win.group_filter.addItems(groups)
        idx = win.group_filter.findText(current)
        win.group_filter.setCurrentIndex(idx if idx >= 0 else 0)
        win.group_filter.blockSignals(False)

    # ---------- Filtro / búsqueda ----------

    def filter_current_list(self):
        win = self.win
        current_widget = win.stack.currentWidget()
        if not isinstance(current_widget, QListWidget):
            return

        text = win.search_box.text().strip().lower()
        group = win.group_filter.currentText()

        for i in range(current_widget.count()):
            item = current_widget.item(i)
            data = item.data(ROLE_DATA) or {}
            matches_text = text in data.get("name", "").lower()
            if current_widget is win.tv_list:
                matches_group = group == "Todas las categorías" or data.get("group") == group
            elif current_widget is win.fav_list:
                if group == "Todas las carpetas":
                    matches_group = True
                elif group == "Sin carpeta":
                    matches_group = not data.get("group")
                else:
                    matches_group = data.get("group") == group
            else:
                matches_group = True
            item.setHidden(not (matches_text and matches_group))

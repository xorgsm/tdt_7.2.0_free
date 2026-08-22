"""
Widgets reutilizables para la interfaz moderna de TDT & Radio VIP.
"""
import hashlib
import random
from collections import deque
from functools import lru_cache

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QWidget

from core.config import get_app_data_dir
from ui import palette
from ui.icons import icon_radio, icon_tv

ROLE_DATA = Qt.UserRole
ROLE_LOGO = Qt.UserRole + 1
ROLE_PLAYING = Qt.UserRole + 2
ROLE_FAV = Qt.UserRole + 3
ROLE_CUSTOM = Qt.UserRole + 4
ROLE_HEALTH = Qt.UserRole + 5

# Paleta de acento por categoría (Deportes, Infantiles, Noticias...). No es
# un mapeo fijo nombre->color: con canales internacionales las categorías
# cambian de un país a otro y mantener esa lista a mano sería interminable.
# En vez de eso, cada nombre de categoría se hashea de forma determinista a
# un color de esta paleta, así que "Deportes" siempre sale del mismo color
# en cada sesión, sin tener que mantener un diccionario.
CATEGORY_PALETTE = (
    palette.ACCENT_CAST,  # verde azulado
    palette.ACCENT_INFO,  # azul cielo
    "#a78bfa",  # lavanda
    "#f472b6",  # rosa
    "#65c46a",  # verde
    palette.ACCENT_CATEGORY_ORANGE,  # naranja
    "#7dd3fc",  # celeste
    "#c084fc",  # violeta
)


@lru_cache(maxsize=256)
def _category_hex(clave: str) -> str:
    idx = int(hashlib.md5(clave.encode("utf-8")).hexdigest(), 16) % len(CATEGORY_PALETTE)
    return CATEGORY_PALETTE[idx]


def category_color(name: str) -> QColor:
    """
    Color estable para una categoría dada (o gris neutro si no hay
    ninguna). El hash MD5 en sí se cachea (_category_hex) porque
    ChannelDelegate.paint() llama a esta función varias veces por fila en
    cada repintado (incluido cada frame de scroll) -- con listas de
    cientos de canales, recalcular el mismo hash para "Deportes" o
    "Generalistas" una y otra vez es trabajo repetido de sobra.

    Se cachea solo el resultado inmutable (el color en hexadecimal), no el
    QColor que se devuelve: el código que llama a esta función hace cosas
    como cat_color.setAlpha(...) sobre lo que le llega, y compartir la
    MISMA instancia de QColor entre llamadas dejaría ese cambio de
    opacidad "pegado" para todas las filas de esa categoría en vez de
    solo la que lo pidió.
    """
    if not name:
        return QColor(palette.TEXT_DIM)
    return QColor(_category_hex(name.strip().lower()))


def rounded_pixmap(pixmap: QPixmap, size: int, radius: int) -> QPixmap:
    """Recorta y redondea un pixmap para usarlo como miniatura de tarjeta."""
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    scaled = scaled.copy(x, y, size, size)

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return rounded


def dominant_color(pixmap: QPixmap) -> QColor | None:
    """
    Color representativo y "vistoso" de un pixmap (normalmente el logo de
    un canal/emisora), para el acento dinámico de "reproduciendo ahora"
    -- ver PlaybackController.update_now_logo(). Ignora píxeles
    transparentes y los casi blancos/negros/grises (el fondo típico de un
    logo en PNG) para no acabar con un gris apagado como "color de marca"
    del canal; si tras filtrar no queda ningún píxel de color, devuelve
    None y quien llama decide un color de reserva.

    Sin librerías de imagen adicionales (Pillow/numpy no son dependencia
    del proyecto): se reduce el pixmap a un tamaño pequeño y se recorren
    sus píxeles a mano vía QImage -- barato para un logo de unos 50px.
    """
    if pixmap.isNull():
        return None
    imagen = pixmap.toImage().scaled(
        24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    ).convertToFormat(QImage.Format_ARGB32)

    suma_r = suma_g = suma_b = 0
    total = 0
    for y in range(imagen.height()):
        for x in range(imagen.width()):
            color = imagen.pixelColor(x, y)
            if color.alpha() < 128:
                continue  # transparente: no es "el logo", es el hueco alrededor
            _h, s, v, _a = color.getHsvF()
            if s < 0.15 or v < 0.12 or v > 0.95:
                continue  # gris / negro / blanco casi puro: mal color de acento
            suma_r += color.red()
            suma_g += color.green()
            suma_b += color.blue()
            total += 1

    if total == 0:
        return None
    return QColor(suma_r // total, suma_g // total, suma_b // total)


class LogoLoader:
    """
    Descarga logos de canales/emisoras en segundo plano y los cachea en
    disco, con un límite de descargas simultáneas.

    Sin ese límite, poblar una lista de tamaño medio (un país con varios
    cientos de canales) con la caché de logos vacía lanzaba una petición
    de red por canal DE GOLPE -- cientos de peticiones HTTP concurrentes
    al mismo servidor, que ralentizan tanto la red como la cola de señales
    del hilo de la interfaz mientras van llegando las respuestas. Es la
    misma familia de problema que podría causar un catálogo mundial de
    miles de canales, a menor escala pero real igualmente con listas de un
    solo país ya grandes.
    Las peticiones de más se encolan y se lanzan según van terminando las
    anteriores, sin cambiar nada de cara a quien llama a load().
    """

    _MAX_CONCURRENTES = 8

    def __init__(self):
        self.manager = QNetworkAccessManager()
        self.cache_dir = get_app_data_dir() / "cache" / "logos"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._replies = []
        self._pendientes = deque()  # URLs únicas pendientes; popleft() es O(1)
        self._solicitudes = {}  # url -> (cache_file, [(callback, size), ...])
        self._en_vuelo = 0

    def load(self, url: str, callback, size: int = 44):
        if not url:
            return
        cache_file = self.cache_dir / (hashlib.md5(url.encode("utf-8")).hexdigest() + ".png")
        if cache_file.exists():
            pix = QPixmap(str(cache_file))
            if not pix.isNull():
                callback(rounded_pixmap(pix, size, size // 4))
                return

        solicitud = self._solicitudes.get(url)
        if solicitud is not None:
            solicitud[1].append((callback, size))
            return

        self._solicitudes[url] = (cache_file, [(callback, size)])
        if self._en_vuelo >= self._MAX_CONCURRENTES:
            self._pendientes.append(url)
            return
        self._lanzar(url)

    def _lanzar(self, url: str):
        cache_file, callbacks = self._solicitudes[url]
        self._en_vuelo += 1
        request = QNetworkRequest(QUrl(url))
        reply = self.manager.get(request)
        self._replies.append(reply)

        def _on_finished():
            pix = QPixmap()
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    data = reply.readAll()
                    if pix.loadFromData(data):
                        pix.save(str(cache_file))
                        redondeados = {}
                        for callback, size in callbacks:
                            logo = redondeados.get(size)
                            if logo is None:
                                logo = rounded_pixmap(pix, size, size // 4)
                                redondeados[size] = logo
                            callback(logo)
            except RuntimeError:
                pass
            finally:
                self._solicitudes.pop(url, None)
                if reply in self._replies:
                    self._replies.remove(reply)
                reply.deleteLater()
                self._en_vuelo -= 1
                self._lanzar_siguiente_pendiente()

        reply.finished.connect(_on_finished)

    def _lanzar_siguiente_pendiente(self):
        while self._pendientes and self._en_vuelo < self._MAX_CONCURRENTES:
            url = self._pendientes.popleft()
            solicitud = self._solicitudes.get(url)
            if solicitud is None:
                continue
            cache_file, callbacks = solicitud
            if cache_file.exists():
                pix = QPixmap(str(cache_file))
                if not pix.isNull():
                    redondeados = {}
                    for callback, size in callbacks:
                        logo = redondeados.get(size)
                        if logo is None:
                            logo = rounded_pixmap(pix, size, size // 4)
                            redondeados[size] = logo
                        callback(logo)
                    self._solicitudes.pop(url, None)
                    continue
            self._lanzar(url)

class EqualizerWidget(QWidget):
    """Ecualizador animado que sustituye al vídeo cuando se escucha radio."""

    # Fracción del salto hacia el nuevo objetivo aleatorio que se recorre en
    # cada frame: rápida al subir (ataque), lenta al bajar (caída) -- el
    # mismo comportamiento asimétrico de un VU-metro real, que es lo que
    # hace que el movimiento se lea como "picos que caen" en vez del
    # parpadeo uniforme y robótico de saltar directo al valor aleatorio
    # cada vez (como hacía antes esta clase).
    _ATAQUE = 0.55
    _CAIDA = 0.18

    def __init__(self, parent=None, bars: int = 9):
        super().__init__(parent)
        self.setObjectName("equalizerWidget")
        self.bars = bars
        self._heights = [0.15] * bars
        # Sin acceso al espectro real de audio (libVLC no lo expone sin
        # callbacks C de bajo nivel, arriesgado de meter sin poder probarlo
        # contra hardware real), el movimiento sigue siendo aleatorio -- pero
        # la AMPLITUD sí sigue al volumen/silencio de verdad (ver
        # set_intensity(), llamado desde PlaybackController en cada cambio
        # de volumen o al silenciar): con el volumen a 0 o en mute, las
        # barras quedan casi planas en vez de moviéndose igual que a
        # volumen alto, que es la señal visual que de verdad importa.
        self._intensity = 1.0
        self.timer = QTimer(self)
        self.timer.setInterval(90)
        self.timer.timeout.connect(self._animate)
        self.setMinimumHeight(200)

    def start(self):
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self._heights = [0.12] * self.bars
        self.update()

    def set_intensity(self, level: float):
        """level: 0.0 (silenciado) a 1.0 (volumen máximo)."""
        self._intensity = max(0.0, min(1.0, level))

    def _animate(self):
        suelo = 0.08
        nuevas = []
        for h in self._heights:
            objetivo = suelo + (random.uniform(0.15, 1.0) - suelo) * self._intensity
            factor = self._ATAQUE if objetivo > h else self._CAIDA
            nuevas.append(h + (objetivo - h) * factor)
        self._heights = nuevas
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = w * 0.12
        usable = w - 2 * margin
        bar_w = usable / (self.bars * 1.8)
        gap = bar_w * 0.8
        x = margin
        base_y = h * 0.78
        max_bar_h = h * 0.5

        for i, hf in enumerate(self._heights):
            bar_h = max_bar_h * hf
            rect = QRectF(x, base_y - bar_h, bar_w, bar_h)
            base_color = QColor(CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)])
            gradient = QLinearGradient(0, base_y - bar_h, 0, base_y)
            gradient.setColorAt(0, base_color.lighter(115))
            gradient.setColorAt(1, base_color.darker(170))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(rect, bar_w / 2, bar_w / 2)
            x += bar_w + gap
        painter.end()


class ChannelGridDelegate(QStyledItemDelegate):
    """
    Tarjeta cuadrada para la vista en cuadrícula de TV (alternativa a
    ChannelDelegate en modo lista, ver el botón junto al filtro de
    categoría en la barra superior de Televisión). Mismo lenguaje visual
    (cristal esmerilado, halo dorado en la que suena) pero pensada para un
    QListWidget en IconMode en vez de una fila ancha.
    """

    CARD_SIZE = 168
    LOGO_RATIO = 0.55

    def sizeHint(self, option, index):
        return QSize(self.CARD_SIZE, self.CARD_SIZE)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(option.rect.adjusted(8, 8, -8, -8))
        radius = 14
        data = index.data(ROLE_DATA) or {}
        is_playing = bool(index.data(ROLE_PLAYING))
        is_fav = bool(index.data(ROLE_FAV))
        is_hover = bool(option.state & QStyle.State_MouseOver)
        logo = index.data(ROLE_LOGO)

        card_path = QPainterPath()
        card_path.addRoundedRect(rect, radius, radius)

        if is_playing:
            fill, border = QColor(58, 46, 20, 225), QColor(233, 195, 96, 170)
        elif is_hover:
            fill, border = QColor(34, 40, 52, 210), QColor(255, 255, 255, 50)
        else:
            fill, border = QColor(20, 25, 34, 190), QColor(255, 255, 255, 18)

        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPath(card_path)

        # Franja de color de categoría junto al borde inferior -- misma
        # idea que el borde de color por categoría de la vista de lista
        # (ChannelDelegate), como una franja horizontal en vez de vertical
        # para encajar mejor con una tarjeta cuadrada. Solo si no está
        # sonando ni en hover: esos dos estados ya tienen su propio
        # lenguaje visual (halo dorado / resalte gris) y no deben competir
        # con el de categoría.
        categoria = data.get("group") or ""
        if categoria and not is_playing and not is_hover:
            cat_color = category_color(categoria)
            cat_color.setAlpha(190)
            alto_franja = 4
            franja = QRectF(
                rect.left() + radius * 0.6, rect.bottom() - alto_franja - 4,
                rect.width() - radius * 1.2, alto_franja,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(cat_color)
            painter.drawRoundedRect(franja, alto_franja / 2, alto_franja / 2)

        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        if is_playing:
            self._draw_glow(painter, rect, radius, QColor("#e9c360"))

        logo_size = min(rect.width(), rect.height()) * self.LOGO_RATIO
        logo_rect = QRectF(rect.center().x() - logo_size / 2, rect.top() + 14, logo_size, logo_size)
        if isinstance(logo, QPixmap) and not logo.isNull():
            painter.drawPixmap(logo_rect.toRect(), logo)
            ring = QColor(233, 195, 96, 150) if is_playing else QColor(255, 255, 255, 30)
            painter.setPen(QPen(ring, 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(logo_rect, 10, 10)
        else:
            placeholder = QLinearGradient(logo_rect.topLeft(), logo_rect.bottomRight())
            placeholder.setColorAt(0, QColor(40, 47, 61, 230))
            placeholder.setColorAt(1, QColor(22, 27, 36, 230))
            painter.setPen(Qt.NoPen)
            painter.setBrush(placeholder)
            painter.drawRoundedRect(logo_rect, 10, 10)
            icon_size = int(logo_size * 0.45)
            icon_pixmap = (
                icon_tv(palette.ACCENT_INFO, size=icon_size)
                if data.get("type") == "tv"
                else icon_radio(palette.ACCENT_CATEGORY_ORANGE, size=icon_size)
            ).pixmap(icon_size, icon_size)
            painter.drawPixmap(
                int(logo_rect.center().x() - icon_size / 2),
                int(logo_rect.center().y() - icon_size / 2),
                icon_pixmap,
            )

        name_rect = QRectF(rect.left() + 8, logo_rect.bottom() + 10, rect.width() - 16, 34)
        font = QFont(painter.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        elided = painter.fontMetrics().elidedText(
            data.get("name", ""), Qt.ElideRight, int(name_rect.width())
        )
        painter.setPen(QColor(palette.ACCENT_LIGHTER) if is_playing else QColor("#ffffff"))
        painter.drawText(name_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

        if is_fav:
            star_rect = QRectF(rect.right() - 26, rect.top() + 4, 20, 20)
            painter.setPen(QColor(palette.ACCENT))
            star_font = QFont(painter.font())
            star_font.setPointSize(11)
            painter.setFont(star_font)
            painter.drawText(star_rect, Qt.AlignCenter, "★")

        painter.restore()

    @staticmethod
    def _draw_glow(painter: QPainter, rect: QRectF, radius: float, color: QColor):
        painter.setBrush(Qt.NoBrush)
        for grow, alpha in ((5, 20), (3, 36)):
            glow_color = QColor(color)
            glow_color.setAlpha(alpha)
            painter.setPen(QPen(glow_color, 1.4))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)


class ChannelDelegate(QStyledItemDelegate):
    """
    Pinta cada fila de canal/emisora como una tarjeta de cristal esmerilado:
    sombra suave por debajo, relleno translúcido con brillo superior, y un
    halo dorado alrededor de la que está sonando. Todo con QPainter puro
    (sin QGraphicsEffect, que no aplica a delegados) capa por capa.
    """

    ROW_HEIGHT = 96
    LOGO_SIZE = 66

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    # ---------- capas de la tarjeta ----------

    @staticmethod
    def _draw_shadow(painter: QPainter, rect: QRectF, radius: float):
        """Sombra por capas: 3 rectángulos descendentes en opacidad, para
        simular un blur barato sin depender de QGraphicsDropShadowEffect."""
        painter.setPen(Qt.NoPen)
        for dy, alpha in ((6, 14), (4, 22), (2, 32)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(rect.translated(0, dy), radius, radius)

    @staticmethod
    def _draw_glow(painter: QPainter, rect: QRectF, radius: float, color: QColor, layers=((7, 16), (4, 28), (2, 48))):
        """Halo exterior: varios trazos crecientes en tamaño y decrecientes
        en opacidad alrededor del borde, para simular un glow suave."""
        painter.setBrush(Qt.NoBrush)
        for grow, alpha in layers:
            glow_color = QColor(color)
            glow_color.setAlpha(alpha)
            painter.setPen(QPen(glow_color, 1.6))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)

    @staticmethod
    def _draw_now_playing_badge(painter: QPainter, logo_rect: QRectF):
        """Circulito dorado con 3 barritas, en la esquina inferior derecha
        del logo, para marcar de un vistazo qué fila es la que suena."""
        size = 20
        badge_rect = QRectF(
            logo_rect.right() - size * 0.7, logo_rect.bottom() - size * 0.7, size, size
        )
        painter.setPen(QPen(QColor(15, 19, 27, 230), 2))
        painter.setBrush(QColor(palette.ACCENT))
        painter.drawEllipse(badge_rect)

        bar_heights = (0.9, 0.5, 0.7)
        bar_w = size * 0.11
        gap = size * 0.08
        total_w = bar_w * 3 + gap * 2
        x = badge_rect.left() + (badge_rect.width() - total_w) / 2
        base_y = badge_rect.bottom() - size * 0.22
        max_h = size * 0.42
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0a0e14"))
        for h_frac in bar_heights:
            bar_h = max_h * h_frac
            painter.drawRoundedRect(QRectF(x, base_y - bar_h, bar_w, bar_h), bar_w / 2, bar_w / 2)
            x += bar_w + gap

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(option.rect.adjusted(8, 6, -8, -8))
        radius = 12
        data = index.data(ROLE_DATA) or {}
        is_playing = bool(index.data(ROLE_PLAYING))
        is_fav = bool(index.data(ROLE_FAV))
        health_status = index.data(ROLE_HEALTH)
        is_hover = bool(option.state & QStyle.State_MouseOver)
        logo = index.data(ROLE_LOGO)

        # ---- sombra suave bajo la tarjeta (siempre, da profundidad) ----
        self._draw_shadow(painter, rect, radius)

        # ---- cristal: relleno degradado + brillo superior, recortado a la
        #      forma redondeada para que el brillo no se salga del borde ----
        card_path = QPainterPath()
        card_path.addRoundedRect(rect, radius, radius)

        if is_playing:
            top_c, bottom_c = QColor(58, 46, 20, 215), QColor(30, 23, 8, 230)
            border_c = QColor(233, 195, 96, 150)
        elif is_hover:
            top_c, bottom_c = QColor(42, 50, 66, 190), QColor(22, 27, 36, 205)
            border_c = QColor(255, 255, 255, 45)
        else:
            top_c, bottom_c = QColor(27, 34, 47, 130), QColor(15, 19, 27, 150)
            border_c = QColor(255, 255, 255, 16)

        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, top_c)
        fill.setColorAt(1, bottom_c)

        painter.save()
        painter.setClipPath(card_path)
        painter.fillPath(card_path, fill)
        # brillo: franja de cristal en la mitad superior, más clara a la
        # izquierda y desvanecida hacia la derecha/abajo.
        shine = QLinearGradient(rect.left(), rect.top(), rect.right() * 0.7, rect.top() + rect.height() * 0.6)
        shine.setColorAt(0.0, QColor(255, 255, 255, 26))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.6), shine)
        painter.restore()

        painter.setPen(QPen(border_c, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        # ---- halo dorado si es la que está sonando; si no, una franja fina
        # del color de su categoría (o carpeta, en Favoritos) siempre
        # visible en el borde izquierdo -- antes ese color solo se veía en
        # el puntito junto al subtítulo; con esto se identifica la
        # categoría de un vistazo en toda la fila, no solo leyendo el texto ----
        categoria = data.get("group") or ""
        if is_playing:
            self._draw_glow(painter, rect, radius, QColor("#e9c360"))
            accent = QRectF(rect.left() + 2, rect.top() + 8, 4, rect.height() - 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(233, 195, 96, 70))
            painter.drawRoundedRect(accent.adjusted(-3, -3, 3, 3), 4, 4)
            painter.setBrush(QColor(palette.ACCENT_LIGHTER))
            painter.drawRoundedRect(accent, 2, 2)
        else:
            if categoria:
                cat_color = category_color(categoria)
                accent = QRectF(rect.left() + 2, rect.top() + 10, 3, rect.height() - 20)
                painter.setPen(Qt.NoPen)
                cat_color.setAlpha(210 if is_hover else 150)
                painter.setBrush(cat_color)
                painter.drawRoundedRect(accent, 1.5, 1.5)
            if is_hover:
                glow_color = category_color(categoria) if categoria else QColor(255, 255, 255)
                self._draw_glow(painter, rect, radius, glow_color, layers=((4, 10), (2, 18)))

        # ---- logo (o placeholder de cristal a juego con la tarjeta) ----
        logo_rect = QRectF(
            rect.left() + 14, rect.center().y() - self.LOGO_SIZE / 2, self.LOGO_SIZE, self.LOGO_SIZE
        )
        if isinstance(logo, QPixmap) and not logo.isNull():
            painter.drawPixmap(logo_rect.toRect(), logo)
            ring = QColor(233, 195, 96, 150) if is_playing else QColor(255, 255, 255, 30)
            painter.setPen(QPen(ring, 1.3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(logo_rect, 10, 10)
        else:
            ph_fill = QLinearGradient(logo_rect.topLeft(), logo_rect.bottomRight())
            ph_fill.setColorAt(0, QColor(40, 47, 61, 230))
            ph_fill.setColorAt(1, QColor(22, 27, 36, 230))
            painter.setPen(Qt.NoPen)
            painter.setBrush(ph_fill)
            painter.drawRoundedRect(logo_rect, 10, 10)
            category_name = data.get("group") or ""
            if category_name:
                # Tinte de color de categoría, translúcido, encima del cristal
                # base: da una pista visual de a qué categoría pertenece el
                # canal incluso antes de que cargue su logo real.
                tint = category_color(category_name)
                tint.setAlpha(75)
                painter.setBrush(tint)
                painter.drawRoundedRect(logo_rect, 10, 10)
            painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(logo_rect, 10, 10)
            # Mismo icono dibujado que el resto de la app (ui/icons.py), con
            # el mismo color que su equivalente en el menú lateral.
            icon_size = int(self.LOGO_SIZE * 0.5)
            if data.get("type") == "tv":
                icon_pixmap = icon_tv(palette.ACCENT_INFO, size=icon_size).pixmap(icon_size, icon_size)
            else:
                icon_pixmap = icon_radio(palette.ACCENT_CATEGORY_ORANGE, size=icon_size).pixmap(icon_size, icon_size)
            icon_x = logo_rect.center().x() - icon_size / 2
            icon_y = logo_rect.center().y() - icon_size / 2
            painter.drawPixmap(int(icon_x), int(icon_y), icon_pixmap)

        # ---- insignia "sonando ahora": circulito con 3 barritas tipo
        # ecualizador sobre la esquina del logo, igual que el badge que
        # ponen Spotify/Apple Music en la carátula de lo que se está
        # reproduciendo. Se suma al halo dorado de la tarjeta -- ese ya
        # avisa de qué fila es, esto identifica de un vistazo qué logo. Se
        # deja estática (sin QTimer) porque un delegado no puede animarse
        # por sí solo sin forzar repintados constantes de toda la lista.
        if is_playing:
            self._draw_now_playing_badge(painter, logo_rect)

        # ---- textos ----
        text_x = logo_rect.right() + 14
        star_reserve = 28 if is_fav else 8
        text_rect = QRectF(text_x, rect.top(), rect.right() - text_x - star_reserve, rect.height())

        name_font = QFont(painter.font())
        name_font.setPointSize(11)
        name_font.setBold(True)
        painter.setFont(name_font)
        name_rect = QRectF(text_rect.left(), text_rect.top() + 15, text_rect.width(), 22)
        elided = painter.fontMetrics().elidedText(data.get("name", ""), Qt.ElideRight, int(name_rect.width()))
        # sombra sutil bajo el texto: un toque de profundidad barato, coherente
        # con el resto de la tarjeta.
        painter.setPen(QColor(0, 0, 0, 90))
        painter.drawText(name_rect.translated(0, 1), Qt.AlignVCenter | Qt.AlignLeft, elided)
        painter.setPen(QColor(palette.ACCENT_LIGHTER) if is_playing else QColor("#ffffff"))
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        # Punto de salud persistente: la comprobación se guarda aparte y
        # no dispara ninguna llamada de red al pintar una fila.
        health_colors = {
            "stable": QColor("#48c78e"),
            "slow": QColor("#f4c95d"),
            "down": QColor("#ef6b73"),
            "restricted": QColor("#ef6b73"),
        }
        if health_status in health_colors:
            health_rect = QRectF(name_rect.right() - 8, name_rect.center().y() - 4, 8, 8)
            painter.setPen(QPen(QColor(10, 14, 20, 210), 1))
            painter.setBrush(health_colors[health_status])
            painter.drawEllipse(health_rect)

        # "subtitle" antes de "group": los canales de TV ahora traen un
        # subtítulo ya compuesto ("Categoría · Ahora: Programa" o solo uno
        # de los dos, ver ChannelListsController._epg_now_text) que debe
        # ganar cuando existe. Radio/historial ya solo rellenaban
        # "subtitle" (bitrate, fecha...) y nunca "group", y Favoritos solo
        # rellena "group" (la carpeta) y nunca "subtitle" -- ninguno de los
        # dos cambia de comportamiento con el orden invertido.
        subtitle = data.get("subtitle") or data.get("group") or ""
        if subtitle:
            sub_font = QFont(painter.font())
            sub_font.setPointSize(8.5)
            sub_font.setBold(False)
            painter.setFont(sub_font)
            sub_rect = QRectF(text_rect.left(), text_rect.top() + 41, text_rect.width(), 16)

            dot_offset = 0
            if data.get("group"):
                dot_size = 6.0
                dot_rect = QRectF(
                    sub_rect.left(), sub_rect.center().y() - dot_size / 2, dot_size, dot_size
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(category_color(data["group"]))
                painter.drawEllipse(dot_rect)
                dot_offset = dot_size + 6

            text_sub_rect = QRectF(
                sub_rect.left() + dot_offset, sub_rect.top(), sub_rect.width() - dot_offset, sub_rect.height()
            )
            painter.setPen(QColor(palette.TEXT_MUTED))
            elided_sub = painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, int(text_sub_rect.width()))
            painter.drawText(text_sub_rect, Qt.AlignVCenter | Qt.AlignLeft, elided_sub)

        # ---- estrella de favorito, con un halo dorado tenue detrás ----
        if is_fav:
            star_rect = QRectF(rect.right() - 26, rect.center().y() - 11, 20, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(201, 162, 39, 45))
            painter.drawEllipse(star_rect.adjusted(-4, -4, 4, 4))
            painter.setPen(QColor(palette.ACCENT))
            star_font = QFont(painter.font())
            star_font.setPointSize(12)
            painter.setFont(star_font)
            painter.drawText(star_rect, Qt.AlignCenter, "\u2605")

        painter.restore()

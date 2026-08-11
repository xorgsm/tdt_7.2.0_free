"""
Iconos dibujados a mano con QPainter — líneas simples, sin texto ni emoji.

Por qué existe este módulo: los iconos anteriores (📺 📻 🕓 📡 🌙 🔊) son emoji
de color que en Windows viven en la fuente "Segoe UI Emoji", separada de
"Segoe UI" (así lo dividió Microsoft hace años). Esta app no fuerza esa
fuente en ningún sitio, así que esos glifos salían como "...". Sustituirlos
por texto ("TV", "FM"...) arregló el problema pero perdía el aspecto de
icono. Dibujando las formas directamente con QPainter no hay ninguna fuente
de por medio: se ven exactamente igual en cualquier instalación de Windows,
tenga los emoji que tenga.

Cada función devuelve un QIcon ya renderizado a un color concreto. Los
botones con estado "activo" (marcado en dorado, texto oscuro) necesitan dos
versiones — una para el fondo oscuro normal y otra para el fondo dorado — y
se cambia el icono al hacer toggle, igual que antes se cambiaba el color del
texto vía QSS ":checked".
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _blank(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def _stroke_painter(pm: QPixmap, color: str, width: float = 1.6) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    return p


def icon_home(color: str, size: int = 26) -> QIcon:
    """Casa sencilla: triángulo de tejado + cuerpo rectangular, mismo trazo
    lineal que el resto de iconos de la barra lateral."""
    pm = _blank(size)
    p = _stroke_painter(pm, color, width=1.6)
    tejado = QPolygonF([
        QPointF(size * 0.14, size * 0.48),
        QPointF(size * 0.50, size * 0.14),
        QPointF(size * 0.86, size * 0.48),
    ])
    p.drawPolyline(tejado)
    cuerpo = QRectF(size * 0.22, size * 0.46, size * 0.56, size * 0.42)
    p.drawRect(cuerpo)
    puerta = QRectF(size * 0.44, size * 0.62, size * 0.14, size * 0.26)
    p.drawRect(puerta)
    p.end()
    return QIcon(pm)


def icon_tv(color: str, size: int = 26) -> QIcon:
    pm = _blank(size)
    p = _stroke_painter(pm, color)
    screen = QRectF(size * 0.09, size * 0.16, size * 0.82, size * 0.54)
    p.drawRoundedRect(screen, 3, 3)
    p.drawLine(QPointF(size * 0.5, screen.bottom()), QPointF(size * 0.5, size * 0.82))
    p.drawLine(QPointF(size * 0.32, size * 0.86), QPointF(size * 0.68, size * 0.86))
    p.end()
    return QIcon(pm)


def icon_radio(color: str, size: int = 26) -> QIcon:
    pm = _blank(size)
    p = _stroke_painter(pm, color)
    body = QRectF(size * 0.12, size * 0.36, size * 0.76, size * 0.50)
    p.drawRoundedRect(body, 4, 4)
    p.drawLine(QPointF(size * 0.30, size * 0.36), QPointF(size * 0.18, size * 0.14))
    p.drawEllipse(QPointF(size * 0.30, size * 0.61), size * 0.085, size * 0.085)
    p.drawLine(QPointF(size * 0.50, size * 0.55), QPointF(size * 0.74, size * 0.55))
    p.drawLine(QPointF(size * 0.50, size * 0.68), QPointF(size * 0.66, size * 0.68))
    p.end()
    return QIcon(pm)


def icon_history(color: str, size: int = 26) -> QIcon:
    pm = _blank(size)
    p = _stroke_painter(pm, color)
    rect = QRectF(size * 0.14, size * 0.14, size * 0.72, size * 0.72)
    p.drawEllipse(rect)
    cx, cy = size * 0.5, size * 0.5
    p.drawLine(QPointF(cx, cy), QPointF(cx, size * 0.28))
    p.drawLine(QPointF(cx, cy), QPointF(size * 0.68, size * 0.58))
    p.end()
    return QIcon(pm)


def icon_cast(color: str, size: int = 26) -> QIcon:
    pm = _blank(size)
    p = _stroke_painter(pm, color)
    origin = QPointF(size * 0.18, size * 0.86)
    for r in (0.22, 0.40, 0.58):
        rect = QRectF(origin.x() - size * r, origin.y() - size * r, size * r * 2, size * r * 2)
        p.drawArc(rect, 40 * 16, 50 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    p.drawEllipse(origin, size * 0.055, size * 0.055)
    p.end()
    return QIcon(pm)


def icon_moon(color: str, size: int = 26) -> QIcon:
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    outer = QPainterPath()
    outer.addEllipse(QRectF(size * 0.16, size * 0.16, size * 0.64, size * 0.64))
    bite = QPainterPath()
    bite.addEllipse(QRectF(size * 0.34, size * 0.10, size * 0.64, size * 0.64))
    crescent = outer.subtracted(bite)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    p.drawPath(crescent)
    p.end()
    return QIcon(pm)


def icon_speaker(color: str, size: int = 26, muted: bool = False) -> QIcon:
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    body = QPolygonF([
        QPointF(size * 0.12, size * 0.38), QPointF(size * 0.30, size * 0.38),
        QPointF(size * 0.50, size * 0.20), QPointF(size * 0.50, size * 0.80),
        QPointF(size * 0.30, size * 0.62), QPointF(size * 0.12, size * 0.62),
    ])
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    p.drawPolygon(body)
    pen = QPen(_qcolor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if muted:
        p.drawLine(QPointF(size * 0.60, size * 0.34), QPointF(size * 0.84, size * 0.66))
        p.drawLine(QPointF(size * 0.84, size * 0.34), QPointF(size * 0.60, size * 0.66))
    else:
        p.drawArc(QRectF(size * 0.54, size * 0.32, size * 0.22, size * 0.36), -60 * 16, 120 * 16)
        p.drawArc(QRectF(size * 0.54, size * 0.22, size * 0.36, size * 0.56), -55 * 16, 110 * 16)
    p.end()
    return QIcon(pm)


def icon_pip(color: str, size: int = 26) -> QIcon:
    """Rectángulo grande (la pantalla) con uno pequeño superpuesto abajo a
    la derecha (la ventana flotante) — el icono estándar de picture-in-picture."""
    pm = _blank(size)
    p = _stroke_painter(pm, color, width=1.5)
    outer = QRectF(size * 0.08, size * 0.16, size * 0.84, size * 0.62)
    p.drawRoundedRect(outer, 3, 3)
    inner = QRectF(size * 0.48, size * 0.46, size * 0.36, size * 0.26)
    p.setBrush(_qcolor(color))
    p.drawRoundedRect(inner, 2, 2)
    p.end()
    return QIcon(pm)


def icon_queue(color: str, size: int = 26) -> QIcon:
    """Icono de "cola de reproducción": tres líneas de listado de ancho
    decreciente con un triángulo de play a la derecha, mismo lenguaje visual
    (trazo + relleno) que icon_speaker."""
    pm = _blank(size)
    p = _stroke_painter(pm, color, width=1.6)
    p.drawLine(QPointF(size * 0.12, size * 0.28), QPointF(size * 0.62, size * 0.28))
    p.drawLine(QPointF(size * 0.12, size * 0.50), QPointF(size * 0.62, size * 0.50))
    p.drawLine(QPointF(size * 0.12, size * 0.72), QPointF(size * 0.44, size * 0.72))
    p.end()
    p2 = QPainter(pm)
    p2.setRenderHint(QPainter.Antialiasing)
    p2.setPen(Qt.NoPen)
    p2.setBrush(_qcolor(color))
    play = QPolygonF([
        QPointF(size * 0.70, size * 0.58),
        QPointF(size * 0.70, size * 0.88),
        QPointF(size * 0.94, size * 0.73),
    ])
    p2.drawPolygon(play)
    p2.end()
    return QIcon(pm)


def icon_library(color: str, size: int = 26) -> QIcon:
    """Icono de "biblioteca": tres barras verticales de alturas distintas,
    como lomos de discos/libros en una estantería."""
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    bars = ((0.16, 0.62), (0.42, 0.30), (0.68, 0.48))
    bar_w = size * 0.16
    base_y = size * 0.82
    for x_frac, h_frac in bars:
        bar_h = size * h_frac
        rect = QRectF(size * x_frac, base_y - bar_h, bar_w, bar_h)
        p.drawRoundedRect(rect, bar_w * 0.3, bar_w * 0.3)
    p.end()
    return QIcon(pm)


def icon_more(color: str, size: int = 26) -> QIcon:
    """Icono de "más opciones": tres puntos horizontales, para el botón
    que agrupa los controles secundarios de la barra de reproducción
    cuando no caben todos en el ancho disponible."""
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    radio = size * 0.07
    centro_y = size * 0.5
    for x_frac in (0.28, 0.5, 0.72):
        cx = size * x_frac
        p.drawEllipse(QRectF(cx - radio, centro_y - radio, radio * 2, radio * 2))
    p.end()
    return QIcon(pm)


def icon_grid_view(color: str, size: int = 26) -> QIcon:
    """Icono de "ver en cuadrícula": cuatro cuadrados en disposición 2x2.

    Sustituye al carácter "⊞" (U+229E) que se usaba antes con setText() en
    ui.main_window.MainWindow.tv_view_toggle -- ese glifo no está garantizado
    en la fuente del sistema (Segoe UI) y en la práctica salía en blanco,
    dejando solo el fondo del botón visible sin ningún icono encima. Mismo
    motivo por el que existe este módulo entero, ver el docstring de arriba.
    """
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    lado = size * 0.34
    hueco = size * 0.14
    origen = size * 0.14
    for fila in range(2):
        for col in range(2):
            x = origen + col * (lado + hueco)
            y = origen + fila * (lado + hueco)
            p.drawRoundedRect(QRectF(x, y, lado, lado), lado * 0.18, lado * 0.18)
    p.end()
    return QIcon(pm)


def icon_list_view(color: str, size: int = 26) -> QIcon:
    """Icono de "ver en lista": tres líneas horizontales con un pequeño
    marcador a la izquierda de cada una, complemento de icon_grid_view()
    para el mismo botón de alternar vista (ver su docstring)."""
    pm = _blank(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(_qcolor(color))
    marcador = size * 0.07
    for y_frac in (0.28, 0.5, 0.72):
        y = size * y_frac
        p.drawEllipse(QRectF(size * 0.14 - marcador, y - marcador, marcador * 2, marcador * 2))
    pen = QPen(_qcolor(color))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    for y_frac in (0.28, 0.5, 0.72):
        y = size * y_frac
        p.drawLine(QPointF(size * 0.30, y), QPointF(size * 0.88, y))
    p.end()
    return QIcon(pm)


def _qcolor(color: str):
    from PySide6.QtGui import QColor
    return QColor(color)

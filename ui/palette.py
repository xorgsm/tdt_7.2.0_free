"""
Paleta de colores compartida por la interfaz — Coder By X@R.

Antes estos valores vivían repetidos como literales sueltos en varios
archivos de ui/ (main_window.py, widgets.py, epg_dialog.py...). Cambiar un tono
obligaba a buscar y tocar cada coincidencia de texto en vez de un solo
sitio; con constantes con nombre, se cambia aquí y se propaga sola.

Los tonos dorados que sí varían con el "color de acento" que el usuario
elige en Configuración > Apariencia siguen resolviéndose en tiempo real vía
ui.style.accent_shades() — este módulo solo cubre los tonos fijos del tema
oscuro (fondos, texto, bordes) y los acentos secundarios por función
(cast, sleep, info...) que no cambian con el acento del usuario.

Uso en código Python (QColor, argumentos de icon_*(), texto de
setStyleSheet() de una sola línea):

    from ui import palette
    QColor(palette.ACCENT)
    icon_tv(palette.ACCENT_INFO)

Los estilos estructurales compartidos se construyen en ui.style. Solo se
mantienen junto al widget los estilos que dependen de datos dinámicos o de
un estado local que no forma parte del sistema visual común.
"""

# ── Fondos ───────────────────────────────────────────────────────────────
BG_ROOT = "#07111c"
BG_PANEL = "#0c1927"
BG_CARD = "#102235"
BG_PANEL_ALT = "#142a3d"
BG_HOVER = "#19344a"
BORDER = "#20384c"
BORDER_STRONG = "#31536d"

# ── Texto ────────────────────────────────────────────────────────────────
TEXT_PRIMARY = "#f3f7fb"
TEXT_SECONDARY = "#bdcbd7"
TEXT_MUTED = "#8297aa"
TEXT_DIM = "#63788a"

# ── Acento de marca (dorado por defecto) ────────────────────────────────
ACCENT = "#c9a227"
ACCENT_LIGHT = "#e8c360"
ACCENT_LIGHTER = "#f4d476"

# ── Semánticos ───────────────────────────────────────────────────────────
DANGER = "#ef5350"
SUCCESS = "#42c985"

# ── Acentos secundarios por función ─────────────────────────────────────
# Cada función tiene su propio color para no confundirse visualmente entre
# sí (cast ≠ favorito ≠ grabando ≠ apagado programado).
ACCENT_CAST = "#31c7b2"
ACCENT_SLEEP = "#9b7bea"
ACCENT_INFO = "#55a7e8"
ACCENT_CATEGORY_ORANGE = "#f39a55"

# ── Guía EPG (rejilla de programación) ──────────────────────────────────
# Celda del programa en emisión ahora mismo vs. resto de celdas de la
# rejilla (ui/epg_dialog.py). Distintos de BG_PANEL/TEXT_SECONDARY porque
# necesitan más contraste dentro de una tabla densa.
EPG_NOW_BG = "#3a2e14"
EPG_CELL_BG = "#171d27"
EPG_CELL_TEXT = "#c7ced8"

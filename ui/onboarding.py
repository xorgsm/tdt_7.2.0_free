"""
Tour breve de bienvenida: se muestra una sola vez, la primera vez que se
abre la app (controlado por settings["onboarding_shown"], ver
core/config.py), señalando un puñado de cosas que no son evidentes a
simple vista -- Ctrl+K, la biblioteca lateral colapsada, el modo PiP...

No es un tutorial paso a paso con flechas señalando la pantalla (mucho
más trabajo y frágil ante cualquier cambio futuro de la interfaz): es una
lista corta de consejos en un diálogo, más barato de mantener y sigue
resolviendo el problema real -- que hay funciones útiles que nadie
descubre solo.

Coder By X@R
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ui import palette
from ui.visual import set_surface

TIPS = (
    ("⌘", "Búsqueda global",
     "Pulsa Ctrl+K en cualquier momento para saltar a cualquier sección o "
     "acción sin tocar el ratón."),
    ("☰", "Biblioteca lateral",
     "El botón de abajo del todo en el riel izquierdo abre un panel con tus "
     "carpetas de favoritos y lo último visto -- está oculto por defecto "
     "para no ocupar sitio si no lo usas."),
    ("⧉", "Ventana flotante (PiP)",
     "El icono junto a pantalla completa saca el vídeo a una ventana "
     "pequeña siempre visible, para seguir viendo mientras usas otra cosa."),
    ("★", "Arrastra tus favoritos",
     "En la pestaña Favoritos puedes arrastrar las filas para reordenarlas "
     "a tu gusto -- el orden se guarda solo."),
    ("⏾", "Apagado programado",
     "El icono de luna pone un temporizador para dejar de reproducir solo, "
     "sin tener que acordarte de apagarlo tú."),
)


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_surface(self, "dialog")
        self.setWindowTitle("Bienvenido a TDT & Radio VIP")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        titulo = QLabel("Antes de empezar, 5 cosas rápidas")
        titulo.setStyleSheet(f"color: {palette.ACCENT}; font-size: 14pt; font-weight: 700;")
        root.addWidget(titulo)

        for glyph, name, desc in TIPS:
            row = QHBoxLayout()
            row.setSpacing(12)

            glyph_label = QLabel(glyph)
            glyph_label.setFixedWidth(28)
            glyph_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            glyph_label.setStyleSheet(f"color: {palette.ACCENT}; font-size: 14pt;")
            row.addWidget(glyph_label)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            name_label = QLabel(name)
            name_label.setStyleSheet(f"color: {palette.TEXT_PRIMARY}; font-weight: 700;")
            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8.5pt;")
            text_col.addWidget(name_label)
            text_col.addWidget(desc_label)
            row.addLayout(text_col, stretch=1)

            root.addLayout(row)

        root.addStretch(1)

        ok_btn = QPushButton("Entendido, ¡vamos!")
        ok_btn.setObjectName("primaryButton")
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        root.addWidget(ok_btn)

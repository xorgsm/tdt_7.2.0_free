"""
Aviso flotante ("toast") no bloqueante, con un botón opcional de
"Deshacer" -- pensado para reemplazar los QMessageBox.question() de
confirmación antes de borrar algo, que interrumpían el flujo con un
diálogo modal. Con esto, la acción se hace ya (más rápido), y si el
usuario se arrepiente, tiene unos segundos para deshacerla con un clic
en vez de tener que rehacer todo a mano.

Coder By X@R
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.visual import set_surface, set_variant

_DEFAULT_TIMEOUT_MS = 6000


class Toast(QFrame):
    """Aviso flotante anclado a la esquina inferior de `parent`."""

    def __init__(self, parent: QWidget, message: str, undo_text: str = "", on_undo=None,
                 timeout_ms: int = _DEFAULT_TIMEOUT_MS):
        super().__init__(parent)
        self.setObjectName("toastNotice")
        set_surface(self, "floating")
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 10)
        layout.setSpacing(12)

        label = QLabel(message)
        label.setObjectName("toastMessage")
        layout.addWidget(label, stretch=1)

        if on_undo is not None:
            undo_btn = QPushButton(undo_text or "Deshacer")
            undo_btn.setObjectName("toastAction")
            set_variant(undo_btn, "primary")
            undo_btn.setCursor(Qt.PointingHandCursor)
            undo_btn.clicked.connect(self._on_undo_clicked)
            layout.addWidget(undo_btn)
            self._on_undo = on_undo
        else:
            self._on_undo = None

        close_btn = QPushButton("✕")
        close_btn.setObjectName("toastClose")
        set_variant(close_btn, "ghost")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.adjustSize()
        self._reposition()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(timeout_ms)

        self.show()
        self.raise_()

    def _on_undo_clicked(self):
        if self._on_undo is not None:
            try:
                self._on_undo()
            finally:
                self._on_undo = None  # una sola vez, por si el clic llega dos veces
        self.close()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 24
        x = parent.width() - self.width() - margin
        y = parent.height() - self.height() - margin
        self.move(max(0, x), max(0, y))


def show_toast(parent: QWidget, message: str, undo_text: str = "", on_undo=None,
               timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> Toast:
    """
    Muestra el aviso y devuelve la instancia (normalmente no hace falta
    guardarla: se destruye sola al cerrarse gracias a WA_DeleteOnClose).

    Si ya había un toast anterior visible sobre el mismo `parent`, se
    cierra antes de mostrar el nuevo -- así no se van acumulando avisos
    superpuestos con borrados seguidos.
    """
    anterior = getattr(parent, "_active_toast", None)
    if anterior is not None:
        try:
            anterior.close()
        except RuntimeError:
            pass  # ya se había destruido solo

    toast = Toast(parent, message, undo_text=undo_text, on_undo=on_undo, timeout_ms=timeout_ms)
    parent._active_toast = toast
    return toast

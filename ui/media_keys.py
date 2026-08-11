"""
Atajos de teclado multimedia del sistema: play/pausa, siguiente, anterior
y detener funcionan aunque la ventana esté minimizada o sin foco — igual
que con Spotify o el reproductor de Windows.

Usa RegisterHotKey vía ctypes en vez de capturar Qt.Key_MediaPlay en un
keyPressEvent normal: ese evento solo llega si la ventana tiene el foco de
teclado, y el objetivo es que las teclas multimedia controlen la app
aunque esté en segundo plano.

Se registra con hWnd=None a propósito: así Windows postea el mensaje
WM_HOTKEY a la cola de mensajes del hilo en vez de a una ventana concreta,
y basta con instalar un QAbstractNativeEventFilter sobre QApplication para
interceptarlo — no hace falta que MainWindow tenga un nativeEvent() propio.

NOTA: esta pieza depende de la API nativa de Windows (RegisterHotKey,
WM_HOTKEY) y no se puede probar en un entorno sin Windows real. Falla en
silencio (start() devuelve False) si algo no cuadra, para no romper el
arranque de la app en caso de que Windows la tenga ya reservada otro
programa — probar en un PC Windows real antes de dar esto por bueno.

Coder By X@R
"""
import ctypes
import ctypes.wintypes
import sys
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

MOD_NOREPEAT = 0x4000

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

WM_HOTKEY = 0x0312

HOTKEY_PLAY_PAUSE = 1001
HOTKEY_STOP = 1002
HOTKEY_NEXT = 1003
HOTKEY_PREV = 1004

_VK_BY_ID = {
    HOTKEY_PLAY_PAUSE: VK_MEDIA_PLAY_PAUSE,
    HOTKEY_STOP: VK_MEDIA_STOP,
    HOTKEY_NEXT: VK_MEDIA_NEXT_TRACK,
    HOTKEY_PREV: VK_MEDIA_PREV_TRACK,
}


def _disponible() -> bool:
    return sys.platform == "win32"


class _MSG(ctypes.Structure):
    """
    Estructura MSG de Win32. ctypes.wintypes no la incluye en todas las
    versiones de Python, así que se define aquí a mano en vez de asumir
    que ctypes.wintypes.MSG existe.
    """
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "SystemMediaKeys"):
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", "windows_generic_MSG"):
            return False, 0
        try:
            addr = int(message)
            msg = _MSG.from_address(addr)
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            self._manager._on_hotkey(msg.wParam)
        return False, 0


class SystemMediaKeys:
    """
    Registra las teclas multimedia del teclado como atajos globales de
    Windows. bind() asocia cada tecla (HOTKEY_PLAY_PAUSE, etc.) a una
    función; start()/stop() activan y liberan el registro.
    """

    def __init__(self):
        self._callbacks: dict[int, Callable] = {}
        self._filter: Optional[_HotkeyFilter] = None
        self._registered = False

    def bind(self, hotkey_id: int, callback: Callable):
        self._callbacks[hotkey_id] = callback

    def start(self) -> bool:
        if not _disponible() or self._registered:
            return False
        try:
            user32 = ctypes.windll.user32
            user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
            user32.RegisterHotKey.argtypes = [
                ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
            ]
            todo_ok = True
            for hotkey_id, vk in _VK_BY_ID.items():
                if not user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, vk):
                    todo_ok = False

            self._filter = _HotkeyFilter(self)
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)

            self._registered = True
            return todo_ok
        except Exception:
            return False

    def stop(self):
        if not self._registered:
            return
        try:
            user32 = ctypes.windll.user32
            for hotkey_id in _VK_BY_ID:
                user32.UnregisterHotKey(None, hotkey_id)
            app = QCoreApplication.instance()
            if app is not None and self._filter is not None:
                app.removeNativeEventFilter(self._filter)
        except Exception:
            pass
        finally:
            self._registered = False
            self._filter = None

    def _on_hotkey(self, hotkey_id: int):
        callback = self._callbacks.get(hotkey_id)
        if callback:
            try:
                callback()
            except Exception:
                pass

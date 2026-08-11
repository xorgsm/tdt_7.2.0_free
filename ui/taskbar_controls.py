"""
Controles de miniatura en la barra de tareas de Windows.

Añade 5 botones (anterior, play/pausa, stop, silencio, siguiente) en la
previsualización que aparece al pasar el ratón sobre el icono de la app
en la barra de tareas, igual que hace Spotify o Windows Media Player.

Usa la interfaz COM ITaskbarList3 directamente vía ctypes, porque
QWinTaskbarButton fue eliminado en PySide6 (solo existía en PySide2).
Si se ejecuta en un sistema que no es Windows, todo falla en silencio.

Coder By X@R
"""
import ctypes
import ctypes.wintypes
import os
import sys
from typing import Callable, Optional

from core.logger import get_logger

log = get_logger(__name__)


def _disponible() -> bool:
    return sys.platform == "win32"


# ── Icono nativo de la ventana (barra de tareas / Alt+Tab) ─────────────────

WM_SETICON      = 0x0080
ICON_SMALL      = 0
ICON_BIG        = 1
IMAGE_ICON      = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTCOLOR = 0x0000


def set_native_window_icon(hwnd: int, icon_path: str) -> None:
    """
    Fija el icono de la ventana directamente vía WM_SETICON, en vez de
    confiar solo en QWidget.setWindowIcon().

    Con Qt.FramelessWindowHint + WA_TranslucentBackground (el chrome propio
    de esta app, sin barra de título nativa) el icono fijado por Qt a veces
    no llega a propagarse al HICON real de la ventana en Windows — la barra
    de tareas y la vista previa al pasar el ratón muestran entonces un
    icono genérico en blanco en vez del dorado de la app, aunque
    setWindowIcon() se haya llamado correctamente en el lado de Qt. Enviar
    WM_SETICON a mano, con el HWND ya creado (se llama desde showEvent,
    igual que TaskbarControls.setup), evita depender de esa propagación.
    """
    if not _disponible() or not icon_path or not os.path.isfile(icon_path):
        return
    try:
        user32 = ctypes.windll.user32

        # Sin declarar restype, ctypes asume un int de 32 bits para el
        # valor devuelto — en Windows de 64 bits (el único que soporta
        # esta app) un HICON/HANDLE ocupa 64 bits, y el valor real se
        # trunca en silencio. Sin esto, SendMessageW recibía un puntero
        # corrupto: el icono no cambiaba y no saltaba ningún error visible.
        user32.LoadImageW.restype = ctypes.wintypes.HICON
        user32.LoadImageW.argtypes = [
            ctypes.wintypes.HINSTANCE, ctypes.wintypes.LPCWSTR, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]

        hicon_small = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE | LR_DEFAULTCOLOR
        )
        hicon_big = user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE | LR_DEFAULTCOLOR
        )
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)

        # También a nivel de clase de ventana (GCL_HICON/GCL_HICONSM): es lo
        # que lee el explorador para la miniatura/Alt+Tab en algunas
        # versiones de Windows, y no siempre coincide con lo que respeta
        # WM_SETICON por sí solo.
        GCL_HICON = -14
        GCL_HICONSM = -34
        if hasattr(user32, "SetClassLongPtrW"):
            user32.SetClassLongPtrW.restype = ctypes.c_void_p
            user32.SetClassLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            if hicon_big:
                user32.SetClassLongPtrW(hwnd, GCL_HICON, hicon_big)
            if hicon_small:
                user32.SetClassLongPtrW(hwnd, GCL_HICONSM, hicon_small)
    except Exception:
        pass


# ── Constantes de la API de Windows ─────────────────────────────────────────
THBF_ENABLED          = 0x0000
THBF_DISABLED         = 0x0001
THBF_DISMISSONCLICK   = 0x0002
THBF_NOBACKGROUND     = 0x0004
THBF_HIDDEN           = 0x0008
THBN_CLICKED          = 0x1800

# ITaskbarList3 CLSID y IID
_CLSID_TaskbarList  = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
_IID_ITaskbarList3  = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

WM_COMMAND = 0x0111
# c_int32 en vez de c_long a propósito: mismo motivo que _GUID más abajo
# (c_long varía de 4 a 8 bytes según la plataforma de ctypes; HRESULT es
# siempre de 32 bits con signo en la propia definición de Windows).
HRESULT = ctypes.c_int32

# Índices de los botones (en orden de aparición en la miniatura)
BTN_PREV  = 0
BTN_PLAY  = 1
BTN_STOP  = 2
BTN_MUTE  = 3
BTN_NEXT  = 4

# Posición de cada método en la vtable de ITaskbarList3 (hereda de
# IUnknown -> ITaskbarList -> ITaskbarList2 -> ITaskbarList3, en ese
# orden; los índices son estables desde Windows 7 y están documentados en
# shobjidl.h). Se llama a mano vía ctypes porque comtypes no está
# instalado en el entorno de compilación de esta app (PyInstaller lo
# marca como "missing module, delayed, optional" en el build) -- confiar
# en él dejaba este código sin ejecutarse nunca en el .exe real.
_VT_HR_INIT = 3
_VT_THUMB_BAR_ADD_BUTTONS = 15
_VT_THUMB_BAR_UPDATE_BUTTONS = 16
_VT_RELEASE = 2


class _GUID(ctypes.Structure):
    # Tipos de ancho fijo (c_uint32/c_uint16) en vez de c_ulong/c_ushort a
    # propósito: c_ulong varía de tamaño según la plataforma en la que
    # corra ctypes (4 bytes en Windows, 8 en Linux/macOS de 64 bits, por la
    # diferencia LLP64 vs LP64) -- con anchos fijos el struct mide 16 bytes
    # siempre, sin depender de en qué máquina se ejecute o compile.
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_string(text: str) -> Optional[_GUID]:
    """
    Convierte un CLSID/IID en formato texto ("{56FDF344-...}") a la
    estructura binaria GUID de 16 bytes que espera la API COM real.

    El código anterior pasaba directamente un buffer de texto Unicode
    donde CoCreateInstance espera un puntero a esa estructura binaria --
    los bytes de la cadena no coinciden con la representación empaquetada
    del GUID, así que la llamada nunca encontraba la clase registrada y
    devolvía un HRESULT de fallo. CLSIDFromString es la función de la
    propia API de Windows para hacer esa conversión correctamente.
    """
    guid = _GUID()
    try:
        ole32 = ctypes.windll.ole32
        ole32.CLSIDFromString.restype = HRESULT
        ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
        hr = ole32.CLSIDFromString(text, ctypes.byref(guid))
        if hr != 0:
            log.warning("CLSIDFromString(%s) devolvió HRESULT 0x%08X", text, hr & 0xFFFFFFFF)
            return None
        return guid
    except Exception:
        log.exception("No se pudo convertir %s a GUID", text)
        return None


def _vtable_method(com_ptr: int, index: int, restype, argtypes):
    """
    Devuelve una función invocable para el método de índice `index` de la
    vtable de un objeto COM. El primer campo de cualquier objeto COM es
    un puntero a su tabla de funciones virtuales -- de ahí sacamos el
    puntero a función real y lo envolvemos con el prototipo adecuado.
    Sin esto no hay forma de llamar a métodos de ITaskbarList3 sin
    comtypes (que no está disponible, ver más arriba).
    """
    vtable_ptr = ctypes.cast(com_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
    func_ptr = ctypes.cast(
        vtable_ptr + index * ctypes.sizeof(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)
    ).contents.value
    func_type = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return func_type(func_ptr)


def _call_com(com_ptr: int, index: int, restype, argtypes, *args):
    """Atajo: obtiene el método de la vtable y lo llama ya con self incluido."""
    fn = _vtable_method(com_ptr, index, restype, argtypes)
    return fn(com_ptr, *args)


class _THUMBBUTTON(ctypes.Structure):
    _fields_ = [
        ("dwMask",    ctypes.c_uint),
        ("iId",       ctypes.c_uint),
        ("iBitmap",   ctypes.c_uint),
        ("hIcon",     ctypes.wintypes.HICON),
        ("szTip",     ctypes.c_wchar * 260),
        ("dwFlags",   ctypes.c_uint),
    ]


THB_BITMAP  = 0x0001
THB_ICON    = 0x0002
THB_TOOLTIP = 0x0004
THB_FLAGS   = 0x0008


class _MSG(ctypes.Structure):
    """
    Estructura MSG de Win32. ctypes.wintypes no la incluye en todas las
    versiones de Python, así que se define aquí a mano (mismo motivo y
    misma estructura que ui/media_keys.py -- se duplica en vez de
    importarla de allí porque son dos piezas de Win32 independientes que
    no tiene sentido acoplar solo por esto).
    """
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt_x", ctypes.c_int32),
        ("pt_y", ctypes.c_int32),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_int32),
        ("xHotspot", ctypes.c_uint32),
        ("yHotspot", ctypes.c_uint32),
        ("hbmMask", ctypes.wintypes.HBITMAP),
        ("hbmColor", ctypes.wintypes.HBITMAP),
    ]


def _hacer_hicon_texto(texto: str, size: int = 16):
    """
    Crea un HICON con un carácter Unicode centrado sobre fondo transparente.
    Se usa para los botones de la miniatura cuando no hay iconos ICO externos.

    Reescrito de cero: la versión anterior empaquetaba BITMAPINFOHEADER e
    ICONINFO como arrays de enteros/punteros genéricos en vez de
    estructuras reales -- con eso los campos no caían en el offset
    correcto (biPlanes y biBitCount comparten un único hueco de 4 bytes,
    no dos separados; hbmMask/hbmColor ocupan 8 bytes cada uno en Windows
    de 64 bits, no 4 como c_void_p*5 asumía). Y lo más importante: nunca
    llegaba a copiar los píxeles ya dibujados al buffer que reserva
    CreateDIBSection (el puntero de salida ppvBits se descartaba sin
    guardarlo), así que el icono habría salido con memoria sin
    inicializar aunque el resto hubiera sido correcto.
    """
    if not _disponible():
        return None
    try:
        from PySide6.QtGui import QImage, QPainter, QFont, QColor
        from PySide6.QtCore import Qt

        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont("Segoe UI Symbol", int(size * 0.6))
        p.setFont(font)
        p.setPen(QColor(220, 220, 220))
        p.drawText(img.rect(), Qt.AlignCenter, texto)
        p.end()

        # QImage::Format_ARGB32 guarda cada píxel como BGRA en memoria (poco
        # endian) -- el mismo orden que espera un DIB de 32 bpp de Windows,
        # así que se copia directo sin reordenar canales.
        bmp_data = img.bits().tobytes()

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        user32.GetDC.restype = ctypes.wintypes.HDC
        user32.GetDC.argtypes = [ctypes.wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
        gdi32.CreateDIBSection.restype = ctypes.wintypes.HBITMAP
        gdi32.CreateDIBSection.argtypes = [
            ctypes.wintypes.HDC, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p), ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
        ]
        gdi32.CreateBitmap.restype = ctypes.wintypes.HBITMAP
        gdi32.CreateBitmap.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
        ]
        user32.CreateIconIndirect.restype = ctypes.wintypes.HICON
        user32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.restype = ctypes.c_int
        gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]

        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = size
        header.biHeight = -size  # negativo: de arriba a abajo, igual que QImage
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        hdc = user32.GetDC(None)
        p_bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(header), 0, ctypes.byref(p_bits), None, 0)
        user32.ReleaseDC(None, hdc)
        if not hbmp or not p_bits.value:
            return None

        ctypes.memmove(p_bits.value, bmp_data, len(bmp_data))

        mask = gdi32.CreateBitmap(size, size, 1, 1, None)

        icon_info = _ICONINFO()
        icon_info.fIcon = 1
        icon_info.xHotspot = 0
        icon_info.yHotspot = 0
        icon_info.hbmMask = mask
        icon_info.hbmColor = hbmp

        hicon = user32.CreateIconIndirect(ctypes.byref(icon_info))

        # CreateIconIndirect hace sus propias copias internas de los
        # bitmaps -- hay que liberar los originales o se quedan reservados
        # hasta que termine el proceso.
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if mask:
            gdi32.DeleteObject(mask)

        return hicon
    except Exception:
        log.exception("Fallo creando el icono del botón '%s' de la miniatura.", texto)
        return None


class TaskbarControls:
    """
    Gestiona los 5 botones de miniatura en la barra de tareas de Windows.
    Debe instanciarse DESPUÉS de que la ventana principal sea visible
    (su HWND debe existir antes de llamar a setup()).
    """

    # Etiquetas Unicode para los botones (Segoe UI Symbol las renderiza bien)
    _LABELS = {
        BTN_PREV: ("⏮", "Canal anterior"),
        BTN_PLAY: ("▶",  "Reproducir / Pausa"),
        BTN_STOP: ("⏹",  "Detener"),
        BTN_MUTE: ("🔊", "Silencio"),
        BTN_NEXT: ("⏭", "Canal siguiente"),
    }

    def __init__(self):
        self._taskbar = None
        self._hwnd    = None
        self._hicons  = {}
        self._ready   = False
        self._callbacks: dict[int, Callable] = {}

    def setup(self, hwnd: int) -> bool:
        """
        Inicializa ITaskbarList3 y añade los botones.
        Devuelve True si tuvo éxito.

        No se intenta comtypes: no está entre las dependencias instaladas
        en el entorno de compilación de esta app (el build de PyInstaller
        lo marca como "missing module... delayed, optional"), así que esa
        rama nunca llegaba a ejecutarse en el .exe real -- todo pasaba
        siempre por el fallback de ctypes puro, que además tenía dos
        fallos propios (ver _create_taskbar_com y _add_buttons).
        """
        if not _disponible():
            return False
        try:
            self._taskbar = self._create_taskbar_com()
            if not self._taskbar:
                log.warning("No se pudo crear el objeto COM ITaskbarList3.")
                return False
            self._hwnd = hwnd
            self._ready = True
            self._add_buttons()
            return True
        except Exception:
            log.exception("Fallo inicializando los botones de la barra de tareas.")
            return False

    def _create_taskbar_com(self) -> Optional[int]:
        """Crea ITaskbarList3 vía CoCreateInstance + CLSIDFromString."""
        try:
            ctypes.windll.ole32.CoInitialize(None)

            clsid = _guid_from_string(_CLSID_TaskbarList)
            iid = _guid_from_string(_IID_ITaskbarList3)
            if clsid is None or iid is None:
                return None

            ole32 = ctypes.windll.ole32
            ole32.CoCreateInstance.restype = HRESULT
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint32,
                ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
            ]
            CLSCTX_INPROC_SERVER = 1
            obj = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER, ctypes.byref(iid), ctypes.byref(obj)
            )
            if hr != 0 or not obj.value:
                log.warning("CoCreateInstance(ITaskbarList3) devolvió HRESULT 0x%08X", hr & 0xFFFFFFFF)
                return None

            # HrInit debe llamarse antes que cualquier otro método de la
            # interfaz -- así lo documenta Microsoft para ITaskbarList.
            self._com_call(obj.value, _VT_HR_INIT, HRESULT, [])
            return obj.value
        except Exception:
            log.exception("Fallo creando el objeto COM ITaskbarList3.")
            return None

    @staticmethod
    def _com_call(com_ptr: int, index: int, restype, argtypes, *args):
        return _call_com(com_ptr, index, restype, argtypes, *args)

    def _add_buttons(self):
        """Construye los iconos y los añade de verdad a la barra de tareas."""
        if not self._ready or not self._hwnd or not self._taskbar:
            return
        try:
            buttons = (_THUMBBUTTON * 5)()
            for idx, (glyph, tip) in self._LABELS.items():
                hicon = _hacer_hicon_texto(glyph)
                self._hicons[idx] = hicon
                b = buttons[idx]
                b.dwMask  = THB_ICON | THB_TOOLTIP | THB_FLAGS
                b.iId     = idx
                b.hIcon   = hicon or 0
                b.szTip   = tip
                b.dwFlags = THBF_ENABLED

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "CoderByXAR.TDTRadioVIP"
            )

            hr = self._com_call(
                self._taskbar, _VT_THUMB_BAR_ADD_BUTTONS, HRESULT,
                [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.POINTER(_THUMBBUTTON)],
                self._hwnd, 5, buttons,
            )
            if hr != 0:
                log.warning("ThumbBarAddButtons devolvió HRESULT 0x%08X", hr & 0xFFFFFFFF)
        except Exception:
            log.exception("Fallo añadiendo los botones a la miniatura de la barra de tareas.")

    def bind(self, btn_id: int, callback: Callable):
        """Asocia una función al botón con ese índice."""
        self._callbacks[btn_id] = callback

    def on_native_message(self, message_ptr: int) -> bool:
        """
        Punto de entrada desde MainWindow.nativeEvent(): recibe el puntero
        bruto al MSG de Win32 que reenvía Qt, lo interpreta y, si es un
        clic en un botón de la miniatura, delega en on_windows_message().
        Devuelve True si el mensaje era eso (para que nativeEvent lo dé
        por consumido).
        """
        if not self._ready:
            return False
        try:
            msg = _MSG.from_address(message_ptr)
        except Exception:
            return False
        return self.on_windows_message(msg.message, msg.wParam, msg.lParam)

    def on_windows_message(self, msg: int, wparam: int, lparam: int) -> bool:
        """
        Devuelve True si el mensaje era un clic en un botón de miniatura.

        Windows envía WM_COMMAND con HIWORD(wParam) = THBN_CLICKED (0x1800)
        y LOWORD(wParam) = id del botón. La versión anterior comparaba
        HIWORD(wParam) contra (THBN_CLICKED >> 16), que al ser 0x1800 (cabe
        en 16 bits) siempre da 0 -- esa comparación coincidía con
        cualquier WM_COMMAND de HIWORD 0, no solo con clics de miniatura.
        """
        if msg != WM_COMMAND:
            return False
        hiword = (wparam >> 16) & 0xFFFF
        if hiword != THBN_CLICKED:
            return False
        btn_id = wparam & 0xFFFF
        callback = self._callbacks.get(btn_id)
        if callback:
            callback()
            return True
        return False

    def update_play_state(self, playing: bool):
        """Cambia el icono del botón play según el estado actual."""
        label = "⏸" if playing else "▶"
        tip   = "Pausar" if playing else "Reproducir"
        self._update_button(BTN_PLAY, label, tip)

    def update_mute_state(self, muted: bool):
        label = "🔇" if muted else "🔊"
        tip   = "Activar sonido" if muted else "Silencio"
        self._update_button(BTN_MUTE, label, tip)

    def _update_button(self, btn_id: int, glyph: str, tip: str):
        """Actualiza icono y tooltip de un botón ya añadido."""
        if not self._ready or not self._hwnd or not self._taskbar:
            return
        try:
            hicon_anterior = self._hicons.get(btn_id)
            hicon = _hacer_hicon_texto(glyph)
            self._hicons[btn_id] = hicon
            btn = (_THUMBBUTTON * 1)()
            btn[0].dwMask  = THB_ICON | THB_TOOLTIP | THB_FLAGS
            btn[0].iId     = btn_id
            btn[0].hIcon   = hicon or 0
            btn[0].szTip   = tip
            btn[0].dwFlags = THBF_ENABLED

            hr = self._com_call(
                self._taskbar, _VT_THUMB_BAR_UPDATE_BUTTONS, HRESULT,
                [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.POINTER(_THUMBBUTTON)],
                self._hwnd, 1, btn,
            )
            if hr != 0:
                log.warning("ThumbBarUpdateButtons devolvió HRESULT 0x%08X", hr & 0xFFFFFFFF)
            elif hicon_anterior:
                # El icono viejo ya no lo usa la miniatura tras el update
                # correcto -- liberarlo aquí evita ir acumulando HICONs
                # huérfanos con cada play/pausa o silencio/sonido.
                ctypes.windll.user32.DestroyIcon(hicon_anterior)
        except Exception:
            log.exception("Fallo actualizando el botón %s de la miniatura.", btn_id)

    def cleanup(self):
        """Libera el objeto COM y los HICONs creados."""
        if self._taskbar:
            try:
                self._com_call(self._taskbar, _VT_RELEASE, ctypes.c_uint32, [])
            except Exception:
                pass
            self._taskbar = None
        for hicon in self._hicons.values():
            if hicon:
                try:
                    ctypes.windll.user32.DestroyIcon(hicon)
                except Exception:
                    pass
        self._hicons.clear()
        self._ready = False

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para TDT & Radio VIP - VERSION FREE COMPLETA.
Todas las funciones activas, sin splash ni codigo de activacion.
Compilar con:  pyinstaller TDTRadioVIP_Free.spec
"""
import os, sys

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = collect_submodules('pychromecast') + collect_submodules('zeroconf')


def buscar_vlc():
    candidatos = [
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
    ]
    for ruta in candidatos:
        if os.path.isfile(os.path.join(ruta, "libvlc.dll")):
            return ruta
    raise SystemExit(
        "\n[TDTRadioVIP] No se encontro VLC.\n"
        "Instala VLC 64 bits desde https://www.videolan.org/\n"
    )


VLC_DIR = buscar_vlc()
FFMPEG_DIR = os.path.join("resources", "ffmpeg")

if not os.path.isfile(os.path.join(FFMPEG_DIR, "ffmpeg.exe")):
    raise SystemExit(
        "\n[TDTRadioVIP] Falta ffmpeg en resources\\ffmpeg\\ffmpeg.exe\n"
        "Descargalo de https://www.gyan.dev/ffmpeg/builds/\n"
    )

ARIA2_DIR = os.path.join("resources", "aria2")
if not os.path.isfile(os.path.join(ARIA2_DIR, "aria2c.exe")):
    raise SystemExit(
        "\n[TDTRadioVIP] Falta aria2c.exe en resources\\aria2\\aria2c.exe (motor de torrents)\n"
        "Descargalo de https://github.com/aria2/aria2/releases\n"
    )

binaries = [
    (os.path.join(VLC_DIR, "libvlc.dll"), "."),
    (os.path.join(VLC_DIR, "libvlccore.dll"), "."),
]

datas = [
    (os.path.join(VLC_DIR, "plugins"), "plugins"),
    (os.path.join(FFMPEG_DIR, "ffmpeg.exe"), FFMPEG_DIR),
    (os.path.join(ARIA2_DIR, "aria2c.exe"), ARIA2_DIR),
]

# ffprobe.exe (~97 MB) no se usa en el código — solo ffmpeg, en
# core/recorder.py. No aporta nada empaquetado y en --onefile hay que
# descomprimirlo entero en cada arranque.

ICONO = os.path.join("resources", "icon.ico")
if os.path.isfile(ICONO):
    datas.append((ICONO, "resources"))
else:
    ICONO = None

a = Analysis(
    ['main_free.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # Nombre fijo, sin versión (ver el mismo comentario en TDTRadioVIP.spec):
    # necesario para que el instalador pueda sustituir limpiamente una
    # instalación anterior en vez de dejarla abandonada al lado.
    name='TDTRadioVIP_Free',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICONO] if ICONO else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TDTRadioVIP_Free',
)

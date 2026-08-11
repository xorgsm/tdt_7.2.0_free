# TDT & Radio VIP (versión Free) — Coder By X@R

Reproductor de escritorio para Windows que permite ver canales de **TDT
gratuitos** y escuchar **radio online** desde fuentes públicas: favoritos,
historial, grabación de stream, guía de programación (EPG) opcional,
descargas, ecualizador de audio y envío a TV (Chromecast/Google Cast y
DLNA/UPnP).

Esta es la **versión free**: todas las funciones están activas desde el
primer arranque, sin código de activación ni pantalla de bienvenida.

## Fuentes de datos (gratuitas y públicas)

- **TV**: lista m3u pública de [iptv-org](https://github.com/iptv-org/iptv),
  filtrable por país.
- **Radio**: API pública [Radio-Browser](https://api.radio-browser.info/), sin
  necesidad de clave, con miles de emisoras de todo el mundo.
- **EPG (guía de programación)**: opcional. Se configura manualmente desde
  `Configuración > Preferencias` pegando la URL de un XMLTV. Sin URL, la app
  funciona igual, solo sin guía.

La disponibilidad y calidad de cada stream depende de terceros ajenos a esta
aplicación: algunos canales o emisoras pueden caerse o cambiar de URL con el
tiempo. Usa "Archivo > Actualizar canales/emisoras" para refrescar las listas.

## Funciones principales

- Favoritos, historial y colas de reproducción.
- Canales y emisoras propios, o importados desde una lista M3U (menú Archivo).
- Grabación de stream a archivo (requiere ffmpeg).
- Descargas (incluye búsqueda multi-fuente y torrents vía aria2c).
- Guía de programación (EPG) con avisos de inicio de programa.
- Ecualizador de audio (graves/medios/agudos, presets de fábrica de libVLC).
- Envío a TV: Chromecast/Google Cast y, como alternativa, TV con DLNA/UPnP
  (la mayoría de Smart TV de fábrica, aunque no tengan Google Cast integrado).
- Modo "solo audio" para canales de TV, vista en cuadrícula o lista, perfiles
  de usuario independientes, tema oscuro con color de acento personalizable.

## Requisitos previos (en el PC donde se ejecute)

1. **Python 3.12** (PyInstaller da problemas con 3.14+).
2. **VLC Media Player** instalado (64 bits): https://www.videolan.org/ — la
   app usa `libvlc` de tu instalación de VLC para reproducir HLS/m3u8.
3. **ffmpeg**, solo si quieres poder grabar streams (botón "● Grabar"). Sin
   ffmpeg, todo lo demás funciona igual.

## Instalación (para ejecutar desde código fuente)

```powershell
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecutar

```powershell
python main_free.py
```

## Estructura del proyecto

```
main_free.py            Punto de entrada de la versión free
core/                    Lógica de negocio (sin Qt, salvo QThread/Signal)
  config.py               Rutas y ajustes (%APPDATA%\CoderByXR\TDTRadioVIP)
  channels.py / radio.py   Listas de TV y emisoras de radio
  favorites.py / history.py
  epg.py                   Guía de programación XMLTV (opcional)
  recorder.py              Grabación de stream con ffmpeg
  downloader.py            Descargas y búsqueda multi-fuente
  torrent_client.py        Cliente de torrents vía aria2c (RPC local)
  caster.py / dlna_caster.py   Envío a TV: Chromecast y DLNA/UPnP
player/
  vlc_player.py            Widget de vídeo/audio embebido con libVLC
    (incluye el ecualizador de audio de libVLC)
ui/
  main_window.py           Ventana principal
  *_controller.py           Un controlador por área (reproducción, listas,
                             biblioteca, EPG, cola...)
  style.py / palette.py     Tema oscuro navy + dorado "Coder By X@R"
tests/                    pytest sobre core/ (ver tests/conftest.py)
```

## Compilar a EXE portable con PyInstaller

Requiere VLC 64 bits instalado, y `ffmpeg.exe` / `aria2c.exe` copiados a mano
en `resources/ffmpeg/` y `resources/aria2/` respectivamente (el `.spec`
aborta con un mensaje explícito si falta alguno):

- ffmpeg: https://www.gyan.dev/ffmpeg/builds/
- aria2: https://github.com/aria2/aria2/releases

```powershell
pyinstaller TDTRadioVIP_Free.spec
```

El `.spec` ya se encarga de empaquetar `libvlc.dll`, sus plugins, ffmpeg,
aria2c y el icono — el EXE resultante funciona en PCs sin VLC instalado.

## Tests

```powershell
py -3.12 -m pytest
```

## Notas

- Los datos del usuario (favoritos, historial, listas personalizadas, caché,
  perfiles) se guardan en `%APPDATA%\CoderByXR\TDTRadioVIP\`.
- Puedes añadir canales o emisoras propias desde el menú **Archivo**, o
  editando a mano `tv_channels_custom.json` / `radio_stations_custom.json`
  en esa misma carpeta.

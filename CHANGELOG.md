# Changelog — TDT & Radio VIP (Coder By X@R)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/).

## [7.5.7] — 2026-08-22

### Added
- Estado de salud de streams persistente por perfil
  (`core/stream_health_store.py`): el diagnóstico clasifica cada stream como
  estable, lento, caído o restringido, y la lista muestra un indicador de
  color junto al canal sin volver a comprobarlo. Incluido en las copias de
  seguridad.
- Filtro por estado de stream en TV y Radio: nuevo desplegable junto al de
  categoría (Todos · Estables · Con incidencias · Sin diagnosticar) que
  filtra con los resultados ya guardados del diagnóstico — instantáneo, sin
  red.
- Exportación M3U editable (Archivo > Exportar lista M3U…): tabla de vista
  previa antes de guardar, con opción de desmarcar, quitar o editar nombre,
  URL y categoría de cada entrada sin tocar la biblioteca de la app.
- Biblioteca de grabaciones (Archivo > Biblioteca de grabaciones…): lista
  las grabaciones `.mp4` de TV y `.mka` de radio (recientes primero), abre
  con doble clic, abre su carpeta y borra en lote con confirmación,
  limpiando también el `.log` auxiliar de ffmpeg.

### Changed
- Rendimiento de logos: se eliminó el límite que impedía cargarlos en
  listas grandes; el cargador mantiene una cola con un máximo de ocho
  descargas simultáneas y cada logo repinta solo su fila visible.
- El filtro de problemas del diagnóstico y la limpieza de resultados
  problemáticos actúan también sobre canales lentos y restringidos.
- Al recargar canales o emisoras se reaplica el filtro activo (búsqueda,
  categoría y estado) en vez de mostrar todas las filas.

## [7.5.6] — 2026-08-21

- Búsqueda universal mejorada mediante `Ctrl+K`.
- Búsqueda por nombre, categoría, etiquetas, país y TVG ID.
- Orden por relevancia con contexto de favoritos e historial reciente.
- Resultados recientes disponibles aunque ya no aparezcan en el catálogo actual.
- Mensaje orientativo cuando una consulta no produce resultados.
- Tarjeta «Reproduciendo ahora» en la portada, sincronizada con pausa y reanudación.
- Ventana flotante convertida en mini reproductor más compacto y despejado.
- Corregido el contraste del panel de canales y las celdas vacías de la guía EPG.
- Nuevo diagnóstico concurrente y cancelable de canales y emisoras.
- Informe de estado HTTP, latencia, redirecciones y tipo de contenido, con filtro de problemas.
- Diagnóstico ampliado con resumen TV/radio, ordenación y exportación CSV segura.

## [7.5.5] — 2026-08-21

- Verificación SHA-256 obligatoria para yt-dlp y slskd antes de ejecutarlos.
- Límites de descarga y extracción para herramientas externas.
Este archivo se empieza a mantener a partir de la versión 7.2.0 — no hay
trazabilidad fiable de versiones anteriores más allá de lo que ya vive en
el propio código (comentarios de cabecera, `final-residual-fix-report.md`),
así que no se reconstruye aquí para no inventar fechas ni alcance.

## [7.5.4.1] — 2026-08-21

### Added
- Grabación de emisoras de radio: el botón de grabar (compartido con TV)
  ya funciona también mientras suena una emisora. Antes reventaba nada
  más arrancar porque `Recorder.start()` intentaba montar la marca de agua
  de vídeo (`drawtext` + `libx264`) sobre un stream que no tiene ninguna
  pista de vídeo (`core/recorder.py`). Ahora `start()` recibe el tipo
  (`kind="tv"`/`"radio"`) desde `ui/playback_controller.py`; para radio se
  salta el pipeline de vídeo entero (`-vn -c:a copy`, sin marca de agua) y
  el archivo se guarda como `.mka` en vez de `.mp4` — Matroska admite
  copiar el códec de audio que traiga el stream (MP3, AAC, Opus...) sin
  arriesgarse a un contenedor que lo rechace.

## [7.5.4] — 2026-08-21

### Added
- Conversor "Convertir": acepta ahora el máximo de formatos de audio que
  ffmpeg sabe decodificar de forma habitual, además de WAV/FLAC/AIFF —
  Opus, WebM, OGG/OGA, Matroska Audio (.mka), M4A/AAC, WMA, Monkey's Audio
  (.ape), WavPack (.wv), MP2, AC3 y AMR (`core/audio_converter.py`,
  `ui/audio_converter_panel.py`). El filtro del diálogo de selección se
  genera ahora desde `INPUT_EXTENSIONS` en vez de estar hardcodeado, para
  que no se desincronicen. Sin cambios en el comando de conversión (`-vn`
  ya descarta cualquier pista de vídeo si el contenedor la trajera).

## [7.5.3] — 2026-08-20

### Added
- Conversor "Convertir": acepta también `.aif`/`.aiff` como entrada, además
  de WAV/FLAC (`core/audio_converter.py`, `ui/audio_converter_panel.py`) —
  ffmpeg detecta el formato por contenido, no por extensión.
- Listas de filas (Descargas recientes, Convertidos recientes, Podcasts,
  Soulseek, Torrents) con fuente algo más pequeña (`QLabel#mediaRowTitle`,
  10pt → 9pt) y filas más compactas en Soulseek, para que quepan más
  entradas visibles a la vez.

### Fixed
- Pestaña Soulseek: cancelar una descarga (una fila o "Cancelar todas")
  ahora la quita de la lista en el mismo paso, sin el paso aparte de
  "Borrar completadas" que hacía falta antes. `SoulseekClient.cancelar_descarga()`
  pasa `?remove=true` a la API de slskd — cancela y elimina esa
  transferencia concreta en una sola llamada, sin tocar otras descargas ya
  completadas o con error (a diferencia de `limpiar_completadas()`, que
  borra TODAS las transferencias terminadas de golpe).

## [7.5.2] — 2026-08-20

### Added
- Pestaña "Editor MP3": barra de progreso con % real durante "Unir" (antes
  era indeterminada). La duración de cada MP3 se lee al añadirlo
  (`core/mp3_info.probe`, en segundo plano) para poder estimar la
  duración total esperada; ffmpeg reporta avance con `-progress pipe:1`
  (`out_time_ms`) mientras stderr va a un log temporal aparte, en vez de
  a un segundo PIPE (evita el deadlock clásico de leer dos pipes con un
  único hilo lector). Si algún archivo no tiene duración conocida, la
  barra cae a indeterminada en vez de mostrar un % incorrecto.
- Nueva pestaña "Editar info" en Descargas: ver y editar los tags ID3
  (Título/Artista/Álbum/Año/Género/Pista) de uno o varios MP3
  (`core/mp3_info.py`, `ui/mp3_tag_editor_panel.py`). Reescribe el
  archivo con ffmpeg (`-c copy`, remux sin recodificar) y lo reemplaza
  atómicamente. No usa ffprobe (no empaquetado): lee duración y tags
  parseando la salida de texto de `ffmpeg -i archivo`.

## [7.5.1] — 2026-08-20

### Added
- Nueva pestaña "Convertir" en Descargas: convierte archivos WAV/FLAC a MP3
  (320kbps) con ffmpeg (`core/audio_converter.py`, `ui/audio_converter_panel.py`).
  Selección múltiple de archivos, carpeta de destino configurable, conversión
  secuencial con progreso y cancelación, escritura a temporal + rename
  atómico (mismo patrón que las descargas de yt-dlp).
- Nueva pestaña "Editor MP3" en Descargas: recorta y une varios MP3 en uno
  solo (`core/audio_editor.py`, `ui/mp3_editor_panel.py`), con un
  reproductor de vista previa ligero y propio, solo audio
  (`player/audio_preview.py`, no reutiliza el `VLCPlayer` de vídeo). La
  unión se hace con una sola llamada a ffmpeg: cada segmento se normaliza
  en volumen (`loudnorm`) y se encadena con fundido cruzado (`acrossfade`,
  duración configurable 1–5s) para que no se note ni el corte ni un salto
  de volumen entre pistas.

## [7.5.0] — 2026-08-20

### Added
- Nueva pestaña "Soulseek" en Descargas: buscar y descargar archivos de la
  red Soulseek (`core/soulseek_account.py`, `core/soulseek_client.py`,
  `ui/soulseek_panel.py`). Habla por HTTP con `slskd`, un proceso externo
  descargado bajo demanda desde sus releases oficiales (nunca empaquetado
  ni enlazado: es AGPLv3), igual que ya se hace con `yt-dlp.exe`. Incluye
  selección múltiple de resultados, botones "Cancelar" (por descarga) y
  "Cancelar todas", y "Borrar completadas" para limpiar el historial de
  transferencias terminadas.

### Fixed
- Crash silencioso (sin traceback en `app.log`) al cancelar una descarga de
  Soulseek desde su fila: el botón vivía dentro del widget que la propia
  acción destruía al refrescar la lista, así que Qt volvía a un objeto C++
  ya liberado a mitad de su propia señal. Diferido con `QTimer.singleShot`,
  con test de regresión. Como el cierre no pasaba por `closeEvent()`,
  también dejaba `slskd.exe` huérfano — mismo síntoma que el bug ya
  resuelto con ffmpeg, causa distinta.
- `slskd` podía morir en silencio al arrancar (antes de exponer su API
  HTTP) si su puerto P2P fijo por defecto caía dentro de un rango que
  Windows excluye para aplicaciones (típico con Hyper-V/WSL activados) —
  ahora se pasa explícitamente y se varía junto con el puerto HTTP.
- Búsquedas de términos poco comunes en Soulseek se rendían sin resultados
  aunque la red sí los tuviera, por rendirse en cuanto `slskd` marcaba la
  búsqueda como completa sin haber recibido nada todavía.
- Lentitud creciente en el panel de Soulseek cuanto más se usaba la sesión:
  `slskd` no olvida las descargas ya terminadas por su cuenta, así que la
  lista solo crecía y cada refresco (cada 2s) reconstruía cada vez más
  filas — mitigado con el nuevo botón "Borrar completadas".

## [7.4.0] — 2026-08-17

### Changed
- El botón de navegación seleccionado en el raíl (Inicio/TV/Radio/Favoritos/
  Historial/Descargas) usa ahora el color propio de su sección en vez de
  mostrar siempre el acento elegido por el usuario en Configuración —
  Favoritos sigue siendo la única excepción, a propósito. Las tarjetas del
  carrusel de Inicio (TV/Radio) ganan además un tinte de fondo por
  categoría, no solo el borde inferior que ya tenían.
- La sección "Descargas" del raíl deja de compartir color con el botón de
  "Enviar a Chromecast" (ambos usaban turquesa por accidente); Descargas
  pasa a coral.
- Se corrigió de paso una inconsistencia preexistente: el título de
  "Inicio" e "Historial" usaba un verde/violeta ligeramente distinto al de
  su icono y su color de sección; ahora coinciden en toda la interfaz.

### Fixed
- Ampliada la cobertura de pruebas de `core/config.py` (sistema de
  perfiles, localización de ffmpeg/icono empaquetados) y `core/downloader.py`
  (incluida la clase `SearchWorker`, sin cubrir hasta ahora).

## [7.3.0] — 2026-08-15

### Changed
- Motor de torrents: aria2c (proceso externo + JSON-RPC sobre HTTP local)
  sustituido por **libtorrent** (bindings Python, en el propio proceso de
  la app). Ya no hay ningún binario que descargar, empaquetar ni apagar al
  cerrar la app — se instala como cualquier otra dependencia de pip. La
  API pública de `TorrentClient`/`TorrentInfo`/`paquete_disponible()` no
  cambió, así que `ui/torrent_panel.py` no necesitó tocarse salvo textos.
  Verificado con un torrent público real (metadatos, progreso, pares,
  pausar/reanudar/eliminar) además de la suite de tests con mocks.

### Added
- `eliminar(hash_, borrar_archivos=True)` ahora sí borra los archivos ya
  descargados — con aria2c esto quedaba documentado como limitación sin
  implementar; libtorrent lo soporta de forma nativa.

### Fixed
- Eliminada una clase entera de bug: al no haber ya un proceso externo
  (aria2c.exe) para el motor de torrents, no puede quedar huérfano al
  cerrar la app aunque Windows fuerce el cierre a mitad de un apagado.

## [7.2.0] — 2026-08-15

### Added
- Suite de tests para 9 módulos que no tenían cobertura dedicada:
  `core/bootstrap.py`, `core/logger.py`, `core/torrent_history.py`,
  `core/epg_reminders.py`, `core/recording_schedule.py`,
  `core/torrent_client.py`, `core/caster.py`, `core/dlna_caster.py` y el
  resto de `core/downloader.py` (antes solo cubierta la búsqueda
  multi-fuente). Cobertura total de `core`/`ui`/`player`: 48% → 53%.
- `pytest-cov` para medir cobertura real en vez de estimarla a ojo
  (`pytest --cov=core --cov=ui --cov=player --cov-report=term-missing`).
- Integración continua en GitHub Actions para el repo público
  (`tdt_7.2.0_free`): pytest + ruff en cada push/PR a `main`.
- `ruff` como linter del proyecto (`ruff.toml`), reglas conservadoras
  (pyflakes + pycodestyle, sin reordenar imports).
- Sistema de perfiles de usuario (favoritos/historial/canales propios
  independientes por persona en el mismo PC).

### Fixed
- `core/epg_reminders.check_due()` no persistía en disco la limpieza de
  avisos con hora corrupta o ya caducados hace tiempo, salvo que OTRO
  aviso distinto disparara en esa misma llamada — se quedaban
  reapareciendo indefinidamente. Encontrado escribiendo los tests nuevos
  de este módulo, corregido en el propio código.
- `#muteButton` seguía con un color de icono hardcodeado en vez de usar
  el sistema `uiVariant` ya adoptado por el resto de controles con estado.

### Changed
- `CLAUDE.md` corregido: el build real de PyInstaller es `--onedir` (no
  `--onefile`), y la versión Free excluye explícitamente Descargas y
  Chromecast, no "todo desbloqueado" como decía antes la documentación.

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

- Mejoras internas de seguridad y robustez.

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

## [7.5.3] — 2026-08-20

## [7.5.2] — 2026-08-20

## [7.5.1] — 2026-08-20

## [7.5.0] — 2026-08-20

## [7.4.0] — 2026-08-17

### Changed
- Se corrigió de paso una inconsistencia preexistente: el título de
  "Inicio" e "Historial" usaba un verde/violeta ligeramente distinto al de
  su icono y su color de sección; ahora coinciden en toda la interfaz.

### Fixed
- Ampliada la cobertura de pruebas de `core/config.py` (sistema de
  perfiles, localización de ffmpeg/icono empaquetados) y `core/downloader.py`
  (incluida la clase `SearchWorker`, sin cubrir hasta ahora).

## [7.3.0] — 2026-08-15

## [7.2.0] — 2026-08-15

### Added
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

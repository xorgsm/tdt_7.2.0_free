# Changelog — TDT & Radio VIP (Coder By X@R)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/).
Este archivo se empieza a mantener a partir de la versión 7.2.0 — no hay
trazabilidad fiable de versiones anteriores más allá de lo que ya vive en
el propio código (comentarios de cabecera, `final-residual-fix-report.md`),
así que no se reconstruye aquí para no inventar fechas ni alcance.

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
- Versión Free: "Descargas" y "Enviar a TV" (Chromecast/DLNA) quedaban
  accesibles pese a que la propia app los describe como exclusivos de la
  versión con licencia. Corregido en los 3 puntos de activación
  (`ui/main_window.py`: navegación, botón de cast, paleta de comandos),
  con tests de regresión (`test_visual_contracts.py`).
- `#muteButton` seguía con un color de icono hardcodeado en vez de usar
  el sistema `uiVariant` ya adoptado por el resto de controles con estado.

### Changed
- `CLAUDE.md` corregido: el build real de PyInstaller es `--onedir` (no
  `--onefile`), y la versión Free excluye explícitamente Descargas y
  Chromecast, no "todo desbloqueado" como decía antes la documentación.

### Published
- Código fuente de la versión Free publicado en
  [github.com/xorgsm/tdt_7.2.0_free](https://github.com/xorgsm/tdt_7.2.0_free)
  (excluye `core/license.py`, `tools/keygen.py` y binarios pesados de
  `resources/`).

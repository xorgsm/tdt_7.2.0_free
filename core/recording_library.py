"""Utilidades para mostrar de forma segura las grabaciones del usuario."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


RECORDING_SUFFIXES = frozenset({".mp4", ".mka"})


@dataclass(frozen=True)
class RecordingFile:
    """Metadatos mínimos de una grabación que ya terminó de escribirse."""

    path: Path
    size: int
    modified: float


def list_recordings(directory: str | Path) -> list[RecordingFile]:
    """Devuelve los archivos de grabación, recientes primero.

    Los logs auxiliares de ffmpeg y archivos ajenos se omiten expresamente.
    Una carpeta inexistente simplemente equivale a una biblioteca vacía.
    """
    folder = Path(directory)
    try:
        files = [
            RecordingFile(path=item, size=item.stat().st_size, modified=item.stat().st_mtime)
            for item in folder.iterdir()
            if item.is_file() and item.suffix.casefold() in RECORDING_SUFFIXES
        ]
    except OSError:
        return []
    return sorted(files, key=lambda item: item.modified, reverse=True)

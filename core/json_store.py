"""Lectura y escritura segura de los pequeños almacenes JSON de la app."""
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar


logger = logging.getLogger(__name__)
T = TypeVar("T")


def _unlink_with_logging(path: Path, artifact_kind: str) -> None:
    """Intenta limpiar un artefacto sin ocultar la excepción en curso."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "No se pudo eliminar %s %s",
            artifact_kind,
            path,
            exc_info=True,
        )


def read_json(path: Path, default: T) -> T:
    """Carga JSON o devuelve ``default`` si falta, está corrupto o es ilegible."""
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("JSON corrupto al leer %s", path)
        return default
    except OSError:
        logger.warning("JSON ilegible al leer %s", path)
        return default


def write_json_atomic(path: Path, value: object, *, indent: int | None = None) -> None:
    """Escribe ``value`` en ``path`` sin exponer nunca un JSON parcial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, indent=indent)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            _unlink_with_logging(temporary_path, "el temporal")


def replace_json_files_atomically(
    values: Mapping[Path, object], *, indent: int | None = None
) -> None:
    """Sustituye varios JSON como una única transacción con rollback."""
    prepared: list[tuple[Path, Path, Path | None, bool]] = []
    replaced: list[tuple[Path, Path, Path | None, bool]] = []
    preserved_backups: set[Path] = set()

    try:
        for path, value in values.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            backup_path: Path | None = None
            existed = path.exists()
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    json.dump(value, temporary, ensure_ascii=False, indent=indent)
                    temporary.flush()
                    os.fsync(temporary.fileno())

                if existed:
                    with tempfile.NamedTemporaryFile(
                        dir=path.parent, suffix=".bak", delete=False
                    ) as backup:
                        backup_path = Path(backup.name)
                    shutil.copy2(path, backup_path)

                prepared.append((path, temporary_path, backup_path, existed))
            except BaseException:
                for artifact in (temporary_path, backup_path):
                    if artifact is not None:
                        _unlink_with_logging(artifact, "el artefacto preparado")
                raise

        try:
            for item in prepared:
                path, temporary_path, _backup_path, _existed = item
                os.replace(temporary_path, path)
                replaced.append(item)
        except BaseException:
            for path, _temporary_path, backup_path, existed in reversed(replaced):
                try:
                    if existed:
                        assert backup_path is not None
                        os.replace(backup_path, path)
                    else:
                        _unlink_with_logging(path, "el destino nuevo del rollback")
                except OSError:
                    if backup_path is not None:
                        preserved_backups.add(backup_path)
                        logger.error(
                            "Falló el rollback de %s; backup conservado en %s",
                            path,
                            backup_path,
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            "Falló el rollback del destino nuevo %s",
                            path,
                            exc_info=True,
                        )
            raise
    finally:
        for _path, temporary_path, backup_path, _existed in prepared:
            for artifact in (temporary_path, backup_path):
                if artifact is not None and artifact not in preserved_backups:
                    _unlink_with_logging(artifact, "el temporal o backup")

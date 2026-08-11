import json
import os
from pathlib import Path

import pytest

from core import json_store
from core.json_store import read_json, write_json_atomic


def test_write_json_atomic_crea_padre_y_conserva_unicode_legible(tmp_path):
    """Rompería si la escritura no fuera UTF-8, legible o no creara el padre."""
    path = tmp_path / "datos" / "ajustes.json"

    write_json_atomic(path, {"canal": "Málaga", "símbolo": "✓"}, indent=2)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "canal": "Málaga",
        "símbolo": "✓",
    }
    assert "Málaga" in path.read_text(encoding="utf-8")
    assert not list(path.parent.glob("*.tmp"))


def test_write_json_atomic_conserva_archivo_anterior_y_limpia_temporal_si_replace_falla(
    tmp_path, monkeypatch
):
    """Rompería si un fallo final dejara datos parciales o temporales."""
    path = tmp_path / "ajustes.json"
    previous = b'{"version": 1}\n'
    path.write_bytes(previous)

    def fail_replace(_source, _target):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="disco lleno"):
        write_json_atomic(path, {"version": 2})

    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_atomic_registra_temporal_que_no_pudo_limpiar_sin_ocultar_error(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "ajustes.json"
    path.write_text('{"old": true}', encoding="utf-8")
    real_unlink = Path.unlink

    def fail_replace(_source, _target):
        raise OSError("error original")

    def fail_temporary_cleanup(self, *args, **kwargs):
        if self.suffix == ".tmp" and self.exists():
            raise OSError("error eliminando temporal")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_temporary_cleanup)

    with pytest.raises(OSError, match="error original"):
        write_json_atomic(path, {"new": True})

    remaining = list(tmp_path.glob("*.tmp"))
    assert len(remaining) == 1
    assert str(remaining[0]) in caplog.text


def test_replace_json_files_atomically_revierte_todos_si_falla_el_segundo_replace(
    tmp_path, monkeypatch
):
    """Rompería si un fallo intermedio dejara una transacción aplicada a medias."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_before = b'{"version": 1}\n'
    second_before = b'{"version": 2}\n'
    first.write_bytes(first_before)
    second.write_bytes(second_before)
    real_replace = os.replace
    failed = False

    def fail_second_destination(source, target):
        nonlocal failed
        if Path(target) == second and not failed:
            failed = True
            raise OSError("fallo en segundo destino")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second_destination)

    with pytest.raises(OSError, match="fallo en segundo destino"):
        json_store.replace_json_files_atomically(
            {first: {"version": 10}, second: {"version": 20}}
        )

    assert first.read_bytes() == first_before
    assert second.read_bytes() == second_before
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.bak"))


def test_replace_json_files_atomically_sustituye_varios_destinos_y_limpia_artefactos(
    tmp_path,
):
    """Rompería si el éxito dejara algún destino antiguo o artefactos internos."""
    first = tmp_path / "first.json"
    second = tmp_path / "nested" / "second.json"
    first.write_text('{"old": 1}', encoding="utf-8")
    second.parent.mkdir()
    second.write_text('["old"]', encoding="utf-8")

    json_store.replace_json_files_atomically(
        {first: {"new": "á"}, second: ["new"]}, indent=2
    )

    assert json.loads(first.read_text(encoding="utf-8")) == {"new": "á"}
    assert json.loads(second.read_text(encoding="utf-8")) == ["new"]
    assert "á" in first.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.bak"))


def test_replace_json_files_atomically_crea_un_destino_nuevo(tmp_path):
    """Rompería si la transacción solo aceptara archivos preexistentes."""
    new_path = tmp_path / "new" / "data.json"

    json_store.replace_json_files_atomically({new_path: [1, 2, 3]})

    assert json.loads(new_path.read_text(encoding="utf-8")) == [1, 2, 3]
    assert not list(new_path.parent.glob("*.tmp"))
    assert not list(new_path.parent.glob("*.bak"))


def test_replace_json_files_atomically_no_toca_destinos_si_falla_la_preparacion(
    tmp_path, monkeypatch
):
    """Rompería si empezara a sustituir antes de preparar todos los archivos."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_before = b'{"old": 1}\n'
    second_before = b'{"old": 2}\n'
    first.write_bytes(first_before)
    second.write_bytes(second_before)
    real_copy2 = json_store.shutil.copy2
    real_replace = os.replace
    copies = 0
    replaces = 0

    def fail_second_backup(source, target):
        nonlocal copies
        copies += 1
        if copies == 2:
            raise OSError("fallo preparando backup")
        return real_copy2(source, target)

    def count_replace(source, target):
        nonlocal replaces
        replaces += 1
        return real_replace(source, target)

    monkeypatch.setattr(json_store.shutil, "copy2", fail_second_backup)
    monkeypatch.setattr(json_store.os, "replace", count_replace)

    with pytest.raises(OSError, match="fallo preparando backup"):
        json_store.replace_json_files_atomically(
            {first: {"new": 1}, second: {"new": 2}}
        )

    assert first.read_bytes() == first_before
    assert second.read_bytes() == second_before
    assert replaces == 0
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.bak"))


def test_replace_json_files_atomically_preserva_error_original_si_rollback_falla(
    tmp_path, monkeypatch, caplog
):
    """Rompería si un error secundario de rollback ocultara el fallo de escritura."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"old": 1}', encoding="utf-8")
    second.write_text('{"old": 2}', encoding="utf-8")
    real_replace = os.replace
    rollback_attempted = False

    def fail_commit_and_rollback(source, target):
        nonlocal rollback_attempted
        source_path = Path(source)
        target_path = Path(target)
        if target_path == second:
            raise OSError("error original")
        if target_path == first and source_path.suffix == ".bak":
            rollback_attempted = True
            raise OSError("error de rollback")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_commit_and_rollback)

    with pytest.raises(OSError, match="error original"):
        json_store.replace_json_files_atomically(
            {first: {"new": 1}, second: {"new": 2}}
        )

    assert rollback_attempted
    assert not list(tmp_path.glob("*.tmp"))
    remaining_backups = list(tmp_path.glob("*.bak"))
    assert len(remaining_backups) == 1
    assert remaining_backups[0].read_text(encoding="utf-8") == '{"old": 1}'
    assert str(remaining_backups[0]) in caplog.text


def test_replace_json_files_atomically_elimina_destino_nuevo_durante_rollback(
    tmp_path, monkeypatch
):
    """Rompería si el rollback dejara un archivo que no existía al empezar."""
    new_path = tmp_path / "new.json"
    existing = tmp_path / "existing.json"
    existing_before = b'{"old": true}\n'
    existing.write_bytes(existing_before)
    real_replace = os.replace

    def fail_existing_destination(source, target):
        if Path(target) == existing and Path(source).suffix == ".tmp":
            raise OSError("fallo tras crear destino")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_existing_destination)

    with pytest.raises(OSError, match="fallo tras crear destino"):
        json_store.replace_json_files_atomically(
            {new_path: {"new": True}, existing: {"new": True}}
        )

    assert not new_path.exists()
    assert existing.read_bytes() == existing_before
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.bak"))


def test_replace_json_files_atomically_preserva_error_original_si_cleanup_falla(
    tmp_path, monkeypatch, caplog
):
    """Rompería si un error secundario de limpieza ocultara el fallo de escritura."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"old": 1}', encoding="utf-8")
    second.write_text('{"old": 2}', encoding="utf-8")
    real_replace = os.replace
    real_unlink = Path.unlink
    cleanup_failures = 0

    def fail_second_destination(source, target):
        if Path(target) == second and Path(source).suffix == ".tmp":
            raise OSError("error original")
        return real_replace(source, target)

    def fail_artifact_cleanup(self, *args, **kwargs):
        nonlocal cleanup_failures
        if self.suffix in {".tmp", ".bak"} and self.exists():
            cleanup_failures += 1
            raise OSError("error de cleanup")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_second_destination)
    monkeypatch.setattr(Path, "unlink", fail_artifact_cleanup)

    with pytest.raises(OSError, match="error original"):
        json_store.replace_json_files_atomically(
            {first: {"new": 1}, second: {"new": 2}}
        )

    assert cleanup_failures > 0
    remaining_artifacts = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob("*.bak"))
    assert {artifact.suffix for artifact in remaining_artifacts} == {".tmp", ".bak"}
    assert all(str(artifact) in caplog.text for artifact in remaining_artifacts)


def test_replace_json_files_atomically_no_reemplaza_si_json_dump_falla(
    tmp_path, monkeypatch
):
    """Rompería si un error de serialización alcanzara la fase de commit."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_before = b'{"old": 1}\n'
    second_before = b'{"old": 2}\n'
    first.write_bytes(first_before)
    second.write_bytes(second_before)
    replaces = 0
    real_replace = os.replace

    def count_replace(source, target):
        nonlocal replaces
        replaces += 1
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", count_replace)

    with pytest.raises(TypeError):
        json_store.replace_json_files_atomically(
            {first: {"new": 1}, second: {"not serializable": object()}}
        )

    assert replaces == 0
    assert first.read_bytes() == first_before
    assert second.read_bytes() == second_before
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.bak"))


def test_read_json_devuelve_valor_almacenado(tmp_path):
    """Rompería si la lectura no interpretara el JSON persistido."""
    path = tmp_path / "datos.json"
    path.write_text('{"nombre": "Peña"}', encoding="utf-8")

    assert read_json(path, {}) == {"nombre": "Peña"}


def test_read_json_devuelve_default_si_el_archivo_no_existe(tmp_path):
    """Rompería si la primera ejecución tratara como error la ausencia."""
    default = {"primera_ejecucion": True}

    assert read_json(tmp_path / "ausente.json", default) is default


def test_read_json_devuelve_default_y_registra_json_corrupto(tmp_path, caplog):
    """Rompería si un archivo truncado llegara a la interfaz o se silenciara."""
    path = tmp_path / "corrupto.json"
    path.write_text("{ sin cerrar", encoding="utf-8")

    assert read_json(path, []) == []
    assert "corrupto" in caplog.text.lower()


def test_read_json_devuelve_default_y_registra_error_de_disco(tmp_path, monkeypatch, caplog):
    """Rompería si un error de lectura de disco interrumpiera el arranque."""
    path = tmp_path / "ilegible.json"
    path.write_text("{}", encoding="utf-8")

    original_open = type(path).open

    def fail_open(self, *_args, **_kwargs):
        if self == path:
            raise OSError("acceso denegado")
        return original_open(self, *_args, **_kwargs)

    monkeypatch.setattr(type(path), "open", fail_open)

    assert read_json(path, {"seguro": True}) == {"seguro": True}
    assert "ilegible" in caplog.text.lower()


def test_read_json_devuelve_default_y_registra_utf8_invalido(tmp_path, caplog):
    """Rompería si bytes corruptos abortaran el arranque al decodificar UTF-8."""
    path = tmp_path / "utf8-invalido.json"
    path.write_bytes(b'{"nombre": "\xff"}')

    assert read_json(path, {"seguro": True}) == {"seguro": True}
    assert "corrupto" in caplog.text.lower()

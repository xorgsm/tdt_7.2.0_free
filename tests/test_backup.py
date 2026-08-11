"""
Pruebas de core/backup.py: export_backup()/import_backup() deben poder
ir y volver sin perder datos, ignorar archivos que no existen, y rechazar
con un mensaje claro un archivo que no sea un backup de esta app.
"""
import json

import pytest

from core import backup as backup_module
from core.backup import export_backup, import_backup
from core.config import get_app_data_dir


def test_export_solo_incluye_lo_que_existe(tmp_path):
    (get_app_data_dir() / "settings.json").write_text(
        json.dumps({"volume": 55}), encoding="utf-8"
    )
    # favorites.json, history.json, etc. NO se crean a propósito.

    destino = tmp_path / "backup.json"
    export_backup(str(destino))

    contenido = json.loads(destino.read_text(encoding="utf-8"))
    assert contenido["settings"] == {"volume": 55}
    assert "favorites" not in contenido
    assert contenido["app"] == "TDT & Radio VIP"


def test_export_omite_una_fuente_corrupta_sin_abortar_el_backup(tmp_path):
    """Rompería si un JSON corrupto impidiera exportar las demás secciones."""
    (get_app_data_dir() / "settings.json").write_text("{ roto", encoding="utf-8")
    destino = tmp_path / "backup.json"

    export_backup(str(destino))

    contenido = json.loads(destino.read_text(encoding="utf-8"))
    assert contenido["backup_format_version"] == 1
    assert "settings" not in contenido


def test_export_omite_una_fuente_con_utf8_invalido(tmp_path):
    """Rompería si bytes no UTF-8 abortaran toda la exportación."""
    (get_app_data_dir() / "settings.json").write_bytes(b'{"name": "\xff"}')
    destino = tmp_path / "backup.json"

    export_backup(str(destino))

    contenido = json.loads(destino.read_text(encoding="utf-8"))
    assert contenido["backup_format_version"] == 1
    assert "settings" not in contenido


def test_export_import_roundtrip(tmp_path):
    carpeta = get_app_data_dir()
    (carpeta / "settings.json").write_text(json.dumps({"volume": 77}), encoding="utf-8")
    (carpeta / "favorites.json").write_text(json.dumps(["canal1"]), encoding="utf-8")

    destino = tmp_path / "backup.json"
    export_backup(str(destino))

    # Se "pierden" los originales (simula cambiar de PC) y se restauran.
    (carpeta / "settings.json").write_text(json.dumps({"volume": 0}), encoding="utf-8")
    (carpeta / "favorites.json").unlink()

    restaurado = import_backup(str(destino))

    assert set(restaurado) == {"settings", "favorites"}
    assert json.loads((carpeta / "settings.json").read_text()) == {"volume": 77}
    assert json.loads((carpeta / "favorites.json").read_text()) == ["canal1"]


def test_import_no_modifica_secciones_ausentes(tmp_path):
    """Rompería si importar un backup parcial borrara datos no incluidos."""
    carpeta = get_app_data_dir()
    favorites = carpeta / "favorites.json"
    favorites_before = b'["existente"]\n'
    favorites.write_bytes(favorites_before)
    source = tmp_path / "partial-backup.json"
    source.write_text(
        json.dumps(
            {
                "app": "TDT & Radio VIP",
                "backup_format_version": 1,
                "settings": {"volume": 42},
            }
        ),
        encoding="utf-8",
    )

    restored = import_backup(str(source))

    assert restored == ["settings"]
    assert favorites.read_bytes() == favorites_before


def test_import_rechaza_archivo_que_no_es_backup(tmp_path):
    ajeno = tmp_path / "no_es_un_backup.json"
    ajeno.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    with pytest.raises(ValueError):
        import_backup(str(ajeno))


@pytest.mark.parametrize(
    "header",
    [
        {"app": "Otra aplicación", "backup_format_version": 1},
        {"app": "TDT & Radio VIP"},
        {"app": "TDT & Radio VIP", "backup_format_version": 2},
        {"app": "TDT & Radio VIP", "backup_format_version": True},
        {"app": "TDT & Radio VIP", "backup_format_version": 1.0},
    ],
)
def test_import_rechaza_cabecera_o_version_invalida_sin_cambiar_destinos(
    tmp_path, header
):
    """Rompería si una cabecera incompatible alcanzara los datos instalados."""
    settings = get_app_data_dir() / "settings.json"
    before = b'{"volume": 15}\n'
    settings.write_bytes(before)
    source = tmp_path / "invalid-backup.json"
    source.write_text(
        json.dumps({**header, "settings": {"volume": 99}}), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        import_backup(str(source))

    assert settings.read_bytes() == before


@pytest.mark.parametrize(
    "key",
    [
        "favorites",
        "history",
        "custom_tv_channels",
        "custom_radio_stations",
        "torrent_history",
    ],
)
def test_import_valida_todas_las_listas_antes_de_cambiar_settings(tmp_path, key):
    """Rompería si importara ajustes antes de detectar una lista incompatible."""
    settings = get_app_data_dir() / "settings.json"
    before = b'{"volume": 15}\n'
    settings.write_bytes(before)
    source = tmp_path / f"invalid-{key}.json"
    source.write_text(
        json.dumps(
            {
                "app": "TDT & Radio VIP",
                "backup_format_version": 1,
                "settings": {"volume": 99},
                key: {"no": "es una lista"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        import_backup(str(source))

    assert settings.read_bytes() == before


def test_import_rechaza_settings_que_no_sea_diccionario_sin_cambiar_destino(tmp_path):
    """Rompería si settings aceptara cualquier JSON en vez de un objeto."""
    settings = get_app_data_dir() / "settings.json"
    before = b'{"volume": 15}\n'
    settings.write_bytes(before)
    source = tmp_path / "invalid-settings.json"
    source.write_text(
        json.dumps(
            {
                "app": "TDT & Radio VIP",
                "backup_format_version": 1,
                "settings": ["no es un objeto"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        import_backup(str(source))

    assert settings.read_bytes() == before


def test_import_propaga_fallo_de_transaccion_y_no_devuelve_restaurados(
    tmp_path, monkeypatch
):
    """Rompería si import ocultara el fallo o devolviera éxito antes de persistir."""
    source = tmp_path / "backup.json"
    source.write_text(
        json.dumps(
            {
                "app": "TDT & Radio VIP",
                "backup_format_version": 1,
                "settings": {"volume": 99},
                "favorites": ["canal"],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fail_transaction(values, *, indent=None):
        calls.append((dict(values), indent))
        raise OSError("rollback completado")

    monkeypatch.setattr(
        backup_module, "replace_json_files_atomically", fail_transaction, raising=False
    )

    with pytest.raises(OSError, match="rollback completado"):
        import_backup(str(source))

    assert len(calls) == 1
    assert calls[0][1] == 2
    assert {path.name for path in calls[0][0]} == {"settings.json", "favorites.json"}


def test_export_usa_write_json_atomic_con_indent_dos(tmp_path, monkeypatch):
    """Rompería si export volviera a exponer un backup parcial."""
    destination = tmp_path / "backup.json"
    calls = []

    def capture_write(path, value, *, indent=None):
        calls.append((path, value, indent))

    monkeypatch.setattr(
        backup_module, "write_json_atomic", capture_write, raising=False
    )

    export_backup(str(destination))

    assert len(calls) == 1
    assert calls[0][0] == destination
    assert calls[0][1]["app"] == "TDT & Radio VIP"
    assert calls[0][2] == 2

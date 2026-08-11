"""
Pruebas de core/config.py: valores por defecto, persistencia de ajustes,
y migración de instalaciones anteriores al selector de país (ver
_migrate_legacy_country_settings).
"""
import json
from types import SimpleNamespace

from core import config
from core.config import (
    DEFAULT_SETTINGS,
    _LEGACY_TV_PLAYLIST_URL,
    get_app_data_dir,
    load_settings,
    save_settings,
    set_current_profile,
)
from ui import equalizer_dialog
from ui import main_window
from ui import playback_controller


def test_load_settings_sin_archivo_devuelve_defaults():
    settings = load_settings()
    for clave, valor in DEFAULT_SETTINGS.items():
        if clave == "recordings_dir":
            continue  # se rellena aparte, ver siguiente test
        assert settings[clave] == valor


def test_load_settings_rellena_recordings_dir_si_falta():
    settings = load_settings()
    assert settings["recordings_dir"] == str(get_app_data_dir() / "recordings")


def test_save_and_load_roundtrip():
    save_settings({**DEFAULT_SETTINGS, "volume": 42, "tv_country_code": "FR"})
    settings = load_settings()
    assert settings["volume"] == 42
    assert settings["tv_country_code"] == "FR"


def test_migra_tv_playlist_url_legacy():
    """
    Instalaciones de antes del selector de país guardaban la URL de España
    fija como si fuera una anulación manual del usuario. Al cargar, debe
    limpiarse para que el nuevo selector de país (tv_country_code) mande.
    """
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(
        json.dumps({"tv_playlist_url": _LEGACY_TV_PLAYLIST_URL}), encoding="utf-8"
    )

    settings = load_settings()

    assert settings["tv_playlist_url"] == ""
    assert settings["tv_country_code"] == "ES"


def test_no_toca_tv_playlist_url_si_es_anulacion_real_del_usuario():
    """Una URL manual genuina (distinta de la legacy) no debe tocarse."""
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(
        json.dumps({"tv_playlist_url": "https://ejemplo.com/mi_lista.m3u"}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings["tv_playlist_url"] == "https://ejemplo.com/mi_lista.m3u"


def test_migra_radio_country_legacy_spain():
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(json.dumps({"radio_country": "Spain"}), encoding="utf-8")

    settings = load_settings()

    assert "radio_country" not in settings
    assert settings["radio_country_code"] == "ES"


def test_migra_radio_country_legacy_valor_desconocido():
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(json.dumps({"radio_country": "Wonderland"}), encoding="utf-8")

    settings = load_settings()

    assert settings["radio_country_code"] == "ES"


def test_load_settings_archivo_corrupto_no_rompe():
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")

    settings = load_settings()

    assert settings["tv_country_code"] == DEFAULT_SETTINGS["tv_country_code"]


def test_migra_epg_url_antiguo_de_globetvapp_si_nunca_se_toco():
    """
    El EPG de globetvapp (por defecto hasta la 6.4.1) dejó de recibir
    programación nueva -- ver core/epg.py y core/config._migrate_legacy_epg_url.
    Una instalación que se quedó con ese valor exacto (nunca lo cambió a
    mano) debe migrar sola al nuevo por defecto.
    """
    from core.config import _LEGACY_EPG_URL

    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(json.dumps({"epg_url": _LEGACY_EPG_URL}), encoding="utf-8")

    settings = load_settings()

    assert settings["epg_url"] == DEFAULT_SETTINGS["epg_url"]
    assert settings["epg_url"] != _LEGACY_EPG_URL


def test_no_toca_epg_url_personalizada_por_el_usuario():
    ruta = get_app_data_dir() / "settings.json"
    ruta.write_text(
        json.dumps({"epg_url": "https://mi-propia-guia.example.com/epg.xml"}),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings["epg_url"] == "https://mi-propia-guia.example.com/epg.xml"


def test_save_settings_devuelve_true_cuando_la_escritura_atomica_tiene_exito():
    """Rompería si el llamador no pudiera distinguir una persistencia correcta."""
    assert save_settings({**DEFAULT_SETTINGS, "volume": 41}) is True


def test_save_settings_devuelve_false_si_falla_el_disco(monkeypatch):
    """Rompería si un fallo de almacenamiento llegara a propagarse hacia Qt."""
    def fail_write(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(config, "write_json_atomic", fail_write)

    assert save_settings(DEFAULT_SETTINGS.copy()) is False


def test_set_current_profile_devuelve_false_si_no_puede_persistir(monkeypatch):
    """Rompería si el cambio de perfil aparentara éxito tras un fallo de disco."""
    monkeypatch.setattr(config, "save_settings", lambda _settings: False)

    assert set_current_profile("Invitado") is False


def test_playback_registra_fallo_de_guardado_frecuente_sin_dialogo(monkeypatch, caplog):
    """Rompería si mover el volumen ocultara el error de persistencia al soporte."""
    window = SimpleNamespace(
        player=SimpleNamespace(set_volume=lambda value: setattr(window, "volume", value)),
        settings={},
        current_type=None,
        mute_btn=SimpleNamespace(isChecked=lambda: False),
        equalizer=SimpleNamespace(set_intensity=lambda _value: None),
    )
    controller = playback_controller.PlaybackController(window)
    monkeypatch.setattr(playback_controller.cfg, "save_settings", lambda _settings: False)

    controller.on_volume_changed(37)

    assert window.volume == 37
    assert window.settings["volume"] == 37
    assert "no se pudieron guardar" in caplog.text.lower()


def test_equalizador_avisa_si_no_puede_guardar_sin_cerrar_el_dialogo(monkeypatch):
    """Rompería si el error de disco cerrara el ecualizador o quedara invisible."""
    dialog = SimpleNamespace(
        win=SimpleNamespace(settings={}),
        _enabled=True,
        _preamp=2.0,
        _bands=[1.0, -1.0],
    )
    warnings = []
    monkeypatch.setattr(equalizer_dialog.cfg, "save_settings", lambda _settings: False)
    monkeypatch.setattr(
        equalizer_dialog.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    equalizer_dialog.EqualizerDialog._guardar_estado(dialog)

    assert dialog.win.settings["equalizer_bands"] == [1.0, -1.0]
    assert warnings and warnings[0][0] is dialog


def test_preferencias_restaura_estado_y_no_confirma_perfil_si_falla_guardado(monkeypatch):
    """Rompería si Preferencias aplicara en memoria un perfil no persistido."""
    previous_settings = {
        "active_profile": "Default",
        "tv_country_code": "ES",
        "radio_country_code": "ES",
        "accent_color": "#c9a227",
    }
    proposed_settings = {**previous_settings, "active_profile": "Invitado"}
    old_recorder = object()
    window = SimpleNamespace(
        settings=previous_settings,
        downloads_dir="C:/descargas",
        recorder=old_recorder,
        epg=SimpleNamespace(load=lambda: (_ for _ in ()).throw(AssertionError("no debe cargar EPG"))),
    )
    warnings = []
    confirmations = []

    class FakeSettingsDialog:
        def __init__(self, _settings, _parent):
            pass

        def exec(self):
            return main_window.QDialog.Accepted

        def get_settings(self):
            return proposed_settings

    monkeypatch.setattr(main_window, "SettingsDialog", FakeSettingsDialog)
    monkeypatch.setattr(main_window.cfg, "save_settings", lambda _settings: False)
    monkeypatch.setattr(main_window.tv_channels, "playlist_url_for", lambda code: f"url:{code}")
    monkeypatch.setattr(main_window.rec_module, "Recorder", lambda _path: object())
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *args: confirmations.append(args))

    main_window.MainWindow._open_settings(window)

    assert window.settings is previous_settings
    assert window.recorder is old_recorder
    assert len(warnings) == 1
    assert confirmations == []

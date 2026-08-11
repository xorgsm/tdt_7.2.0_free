"""
Pruebas de los perfiles de usuario (core/config.py): el perfil "Default"
debe ser exactamente la carpeta raíz de siempre (retrocompatibilidad), y
los módulos que separan datos por perfil (favoritos, historial, canales/
emisoras personalizadas, grabaciones programadas) deben aislarse entre sí
al cambiar de perfil.
"""
from core import config
from core import favorites as fav_store
from core import history as hist_store


def test_perfil_default_es_la_carpeta_raiz():
    assert config.get_profile_data_dir("Default") == config.get_app_data_dir()


def test_list_profiles_incluye_default_primero():
    assert config.list_profiles() == ["Default"]
    config.create_profile("Familia")
    assert config.list_profiles() == ["Default", "Familia"]


def test_create_profile_hace_carpeta_propia_distinta_de_default():
    config.create_profile("Familia")
    assert config.get_profile_data_dir("Familia") != config.get_app_data_dir()
    assert config.get_profile_data_dir("Familia").is_dir()


def test_favoritos_se_aislan_por_perfil(monkeypatch):
    config.create_profile("Familia")

    monkeypatch.setattr(config, "get_current_profile", lambda: "Default")
    fav_store.toggle_favorite("tv", "La 1", "http://a")

    monkeypatch.setattr(config, "get_current_profile", lambda: "Familia")
    assert fav_store.load_favorites() == []

    monkeypatch.setattr(config, "get_current_profile", lambda: "Default")
    assert len(fav_store.load_favorites()) == 1


def test_historial_se_aisla_por_perfil(monkeypatch):
    config.create_profile("Familia")

    monkeypatch.setattr(config, "get_current_profile", lambda: "Default")
    hist_store.add_entry("tv", "La 1", "http://a")

    monkeypatch.setattr(config, "get_current_profile", lambda: "Familia")
    assert hist_store.load_history() == []


def test_get_current_profile_por_defecto_es_default():
    assert config.get_current_profile() == "Default"


def test_set_current_profile_se_guarda_en_settings():
    config.set_current_profile("Familia")
    assert config.load_settings()["active_profile"] == "Familia"

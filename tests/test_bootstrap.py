"""
Pruebas de core/bootstrap.py: fijar el AppUserModelID no debe explotar
fuera de Windows (ni si la llamada real a Windows falla), y
prepare_bundled_vlc() debe fijar VLC_PLUGIN_PATH solo cuando encuentra
una carpeta "plugins" junto al ejecutable/proyecto.
"""
import os
import sys

from core import bootstrap


def test_set_app_user_model_id_no_hace_nada_fuera_de_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # No debe lanzar excepción aunque no exista nada de Windows aquí.
    bootstrap.set_app_user_model_id("Coder.TDTRadioVIP")


def test_set_app_user_model_id_no_explota_si_falla_la_llamada_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # En una máquina sin ctypes.windll (como este entorno de test), la
    # llamada real falla -- debe quedar atrapada por el except Exception
    # interno en vez de propagar y romper el arranque.
    bootstrap.set_app_user_model_id("Coder.TDTRadioVIP")


def test_prepare_bundled_vlc_fija_plugin_path_si_existe_la_carpeta(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("VLC_PLUGIN_PATH", raising=False)

    bootstrap.prepare_bundled_vlc()

    assert os.environ["VLC_PLUGIN_PATH"] == str(plugins_dir)


def test_prepare_bundled_vlc_no_fija_plugin_path_si_no_existe_la_carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("VLC_PLUGIN_PATH", raising=False)

    bootstrap.prepare_bundled_vlc()

    assert "VLC_PLUGIN_PATH" not in os.environ


def test_bootstrap_llama_a_las_dos_funciones_en_orden(monkeypatch):
    llamadas = []
    monkeypatch.setattr(bootstrap, "set_app_user_model_id", lambda x: llamadas.append(("id", x)))
    monkeypatch.setattr(bootstrap, "prepare_bundled_vlc", lambda: llamadas.append(("vlc",)))

    bootstrap.bootstrap("Coder.TDTRadioVIP")

    assert llamadas == [("id", "Coder.TDTRadioVIP"), ("vlc",)]

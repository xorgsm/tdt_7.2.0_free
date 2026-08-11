"""
Pruebas de core/updater.py: solo debe avisar de una versión más nueva que
la instalada, sin depender de red de verdad (se sustituye requests.get).
"""
from core import updater


class _RespuestaFalsa:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_url_vacia_desactiva_la_comprobacion():
    assert updater.check_for_update("", current_version="6.4.0") is None


def test_version_remota_mas_nueva_devuelve_el_json(monkeypatch):
    monkeypatch.setattr(
        updater.requests, "get",
        lambda *a, **k: _RespuestaFalsa({"version": "6.5.0", "url": "https://example.com"}),
    )
    resultado = updater.check_for_update("https://fake", current_version="6.4.0")
    assert resultado == {"version": "6.5.0", "url": "https://example.com"}


def test_version_remota_igual_o_anterior_no_avisa(monkeypatch):
    monkeypatch.setattr(
        updater.requests, "get",
        lambda *a, **k: _RespuestaFalsa({"version": "6.4.0", "url": "https://example.com"}),
    )
    assert updater.check_for_update("https://fake", current_version="6.4.0") is None

    monkeypatch.setattr(
        updater.requests, "get",
        lambda *a, **k: _RespuestaFalsa({"version": "6.3.0", "url": "https://example.com"}),
    )
    assert updater.check_for_update("https://fake", current_version="6.4.0") is None


def test_fallo_de_red_no_revienta(monkeypatch):
    def _falla(*a, **k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(updater.requests, "get", _falla)
    assert updater.check_for_update("https://fake", current_version="6.4.0") is None


def test_json_sin_version_no_avisa(monkeypatch):
    monkeypatch.setattr(
        updater.requests, "get", lambda *a, **k: _RespuestaFalsa({"url": "https://example.com"})
    )
    assert updater.check_for_update("https://fake", current_version="6.4.0") is None


def test_version_tuple_ignora_sufijos_no_numericos():
    assert updater._version_tuple("6.4.0-beta") == (6, 4, 0)
    assert updater._version_tuple("") == (0,)

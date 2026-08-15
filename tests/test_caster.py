"""
Pruebas de core/caster.py (envío a Chromecast): guess_stream_content_type
como función pura, parseo de rangos HTTP para servir archivos locales
(_SingleFileHandler._parse_range) y LocalFileServer end-to-end sobre un
socket local real (sin red externa ni hardware Chromecast). El
descubrimiento (CastDiscoveryWorker) se prueba sustituyendo
pychromecast.get_chromecasts, sin buscar dispositivos reales en la red.
"""
import http.client

import pytest

from core import caster
from core.caster import CastDiscoveryWorker, LocalFileServer, _SingleFileHandler, guess_stream_content_type


# ── guess_stream_content_type ───────────────────────────────────────────────

@pytest.mark.parametrize("url,kind,esperado", [
    ("https://ejemplo.com/canal.m3u8", "", "application/x-mpegURL"),
    ("https://ejemplo.com/canal.m3u8?token=abc", "", "application/x-mpegURL"),
    ("https://ejemplo.com/hls/m3u8/playlist", "", "application/x-mpegURL"),
    ("https://ejemplo.com/manifest.mpd", "", "application/dash+xml"),
    ("https://ejemplo.com/radio.mp3", "", "audio/mp3"),
    ("https://ejemplo.com/radio.aac", "", "audio/aac"),
    ("https://ejemplo.com/radio.m4a", "", "audio/aac"),
    ("https://ejemplo.com/stream", "radio", "audio/mp3"),
    ("https://ejemplo.com/stream", "", "video/mp4"),
])
def test_guess_stream_content_type(url, kind, esperado):
    assert guess_stream_content_type(url, kind) == esperado


# ── pychromecast_available ──────────────────────────────────────────────────

def test_pychromecast_available_true_si_esta_instalado():
    # El proyecto declara pychromecast como dependencia (requirements.txt);
    # si el import falla aquí, algo se rompió en el entorno de test.
    assert caster.pychromecast_available() is True


# ── _SingleFileHandler._parse_range ─────────────────────────────────────────

def _handler_con_headers(headers: dict) -> _SingleFileHandler:
    handler = _SingleFileHandler.__new__(_SingleFileHandler)
    handler.headers = headers
    return handler


def test_parse_range_sin_cabecera_devuelve_none():
    assert _handler_con_headers({})._parse_range(1000) is None


def test_parse_range_normal():
    handler = _handler_con_headers({"Range": "bytes=100-199"})
    assert handler._parse_range(1000) == (100, 199)


def test_parse_range_sin_fin_llega_hasta_el_final():
    handler = _handler_con_headers({"Range": "bytes=900-"})
    assert handler._parse_range(1000) == (900, 999)


def test_parse_range_sufijo_ultimos_n_bytes():
    handler = _handler_con_headers({"Range": "bytes=-100"})
    assert handler._parse_range(1000) == (900, 999)


def test_parse_range_fin_recortado_al_tamano_del_archivo():
    handler = _handler_con_headers({"Range": "bytes=900-5000"})
    assert handler._parse_range(1000) == (900, 999)


def test_parse_range_invalida_devuelve_none():
    for cabecera in ["bytes=-", "abc", "bytes=abc-def"]:
        assert _handler_con_headers({"Range": cabecera})._parse_range(1000) is None


def test_parse_range_fuera_de_rango_devuelve_none():
    handler = _handler_con_headers({"Range": "bytes=2000-3000"})
    assert handler._parse_range(1000) is None


# ── LocalFileServer (HTTP real en localhost, sin red externa) ───────────────

def test_local_file_server_sirve_archivo_completo(tmp_path):
    contenido = b"contenido de prueba" * 100
    archivo = tmp_path / "video.mp4"
    archivo.write_bytes(contenido)

    server = LocalFileServer()
    try:
        url, content_type = server.serve(str(archivo))
        assert content_type == "video/mp4"

        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request("GET", f"/{archivo.name}")
        resp = conn.getresponse()
        cuerpo = resp.read()
        assert resp.status == 200
        assert cuerpo == contenido
        conn.close()
    finally:
        server.stop()


def test_local_file_server_soporta_range_http_206(tmp_path):
    contenido = b"0123456789" * 10
    archivo = tmp_path / "audio.mp3"
    archivo.write_bytes(contenido)

    server = LocalFileServer()
    try:
        server.serve(str(archivo))

        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request("GET", f"/{archivo.name}", headers={"Range": "bytes=10-19"})
        resp = conn.getresponse()
        cuerpo = resp.read()
        assert resp.status == 206
        assert cuerpo == contenido[10:20]
        conn.close()
    finally:
        server.stop()


def test_local_file_server_head_no_devuelve_cuerpo(tmp_path):
    archivo = tmp_path / "cancion.mp3"
    archivo.write_bytes(b"x" * 500)

    server = LocalFileServer()
    try:
        server.serve(str(archivo))

        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request("HEAD", f"/{archivo.name}")
        resp = conn.getresponse()
        cuerpo = resp.read()
        assert resp.status == 200
        assert cuerpo == b""
        assert resp.getheader("Content-Length") == "500"
        conn.close()
    finally:
        server.stop()


def test_local_file_server_404_si_el_archivo_no_existe(tmp_path):
    server = LocalFileServer()
    try:
        server.serve(str(tmp_path / "no_existe.mp4"))
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request("GET", "/no_existe.mp4")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404
        conn.close()
    finally:
        server.stop()


def test_local_file_server_stop_es_idempotente():
    server = LocalFileServer()
    server.stop()  # nunca se arrancó -- no debe explotar
    server.stop()  # llamar dos veces tampoco


# ── CastDiscoveryWorker (red sustituida, sin buscar hardware real) ─────────

class _FakeChromecast:
    def __init__(self, name):
        self.name = name


def test_cast_discovery_worker_encuentra_dispositivos(monkeypatch):
    fake_devices = [_FakeChromecast("Salón"), _FakeChromecast("Dormitorio")]
    monkeypatch.setattr(
        "pychromecast.get_chromecasts", lambda timeout=8: (fake_devices, "fake_browser")
    )

    worker = CastDiscoveryWorker()
    encontrados = []
    worker.found.connect(encontrados.append)
    worker.run()

    assert encontrados == [["Salón", "Dormitorio"]]
    assert worker.device_by_name("Salón") is fake_devices[0]
    assert worker.device_by_name("Inexistente") is None


def test_cast_discovery_worker_no_explota_si_falla_la_busqueda(monkeypatch):
    def _falla(timeout=8):
        raise OSError("red no disponible")

    monkeypatch.setattr("pychromecast.get_chromecasts", _falla)

    worker = CastDiscoveryWorker()
    encontrados = []
    worker.found.connect(encontrados.append)
    worker.run()

    assert encontrados == [[]]


def test_stop_discovery_es_idempotente(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        "pychromecast.discovery.stop_discovery", lambda browser: llamadas.append(browser)
    )

    worker = CastDiscoveryWorker()
    worker._browser = "fake_browser"

    worker.stop_discovery()
    worker.stop_discovery()  # segunda llamada no debe volver a llamar a stop_discovery

    assert llamadas == ["fake_browser"]

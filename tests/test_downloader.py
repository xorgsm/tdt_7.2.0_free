"""
Pruebas de core/downloader.py más allá de la búsqueda (ver ya
test_downloader_search.py): utilidades de formato, gestión del
ejecutable yt-dlp.exe (descarga atómica, autoactualización) y la parte
de DownloadWorker que no depende de arrancar un proceso real. No
depende de red ni de que exista yt-dlp.exe de verdad -- se sustituyen
urllib.request.urlopen y subprocess.run.
"""
import os
import time

import pytest

from core import downloader


# ── utilidades de formato ────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("123.5", 123.5), ("", None), ("NA", None), ("None", None), ("abc", None), (None, None),
])
def test_num(texto, esperado):
    assert downloader._num(texto) == esperado


@pytest.mark.parametrize("bps,esperado", [
    (0, ""), (None, ""), (500 * 1024, "500 KB/s"), (2 * 1024 * 1024, "2.0 MB/s"),
])
def test_fmt_velocidad(bps, esperado):
    assert downloader._fmt_velocidad(bps) == esperado


@pytest.mark.parametrize("segundos,esperado", [
    (None, ""), (90, "faltan 1:30"), (3661, "faltan 1h 01m"),
])
def test_fmt_eta(segundos, esperado):
    assert downloader._fmt_eta(segundos) == esperado


# ── should_check_update / mark_update_checked ───────────────────────────────

def test_should_check_update_true_sin_registro_previo():
    assert downloader.should_check_update() is True


def test_mark_update_checked_evita_comprobar_de_nuevo_enseguida():
    downloader.mark_update_checked()
    assert downloader.should_check_update() is False


def test_should_check_update_true_si_paso_el_intervalo():
    downloader.mark_update_checked()
    hace_mucho = time.time() - downloader.UPDATE_CHECK_INTERVAL_SECONDS - 10
    downloader._last_check_file().write_text(str(hace_mucho))
    assert downloader.should_check_update() is True


# ── ensure_yt_dlp (descarga atómica: temporal + rename) ─────────────────────

class _FakeHTTPResponse:
    def __init__(self, data: bytes):
        self.headers = {"Content-Length": str(len(data))}
        self._data = data
        self._pos = 0

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ensure_yt_dlp_devuelve_la_ruta_existente_sin_descargar(monkeypatch):
    exe_path = downloader._tools_dir() / "yt-dlp.exe"
    exe_path.write_bytes(b"ya existe")

    def _no_deberia_llamarse(*a, **k):
        raise AssertionError("no debería intentar descargar si ya existe")

    monkeypatch.setattr(downloader.urllib.request, "urlopen", _no_deberia_llamarse)

    assert downloader.ensure_yt_dlp() == str(exe_path)


def test_ensure_yt_dlp_descarga_y_deja_el_archivo_final(monkeypatch):
    contenido = b"contenido binario de yt-dlp" * 1000
    monkeypatch.setattr(
        downloader.urllib.request, "urlopen", lambda *a, **k: _FakeHTTPResponse(contenido)
    )

    progresos = []
    ruta = downloader.ensure_yt_dlp(progress_cb=progresos.append)

    assert os.path.exists(ruta)
    with open(ruta, "rb") as fh:
        assert fh.read() == contenido
    assert progresos[-1] == pytest.approx(1.0)
    # No debe quedar el archivo temporal tras un éxito.
    assert not (downloader._tools_dir() / "yt-dlp.part").exists()


def test_ensure_yt_dlp_limpia_el_parcial_si_falla_la_descarga(monkeypatch):
    def _falla(*a, **k):
        raise OSError("conexion perdida")

    monkeypatch.setattr(downloader.urllib.request, "urlopen", _falla)

    with pytest.raises(OSError):
        downloader.ensure_yt_dlp()

    assert not (downloader._tools_dir() / "yt-dlp.part").exists()


# ── self_update_yt_dlp ───────────────────────────────────────────────────────

class _ResultadoProceso:
    def __init__(self, returncode):
        self.returncode = returncode


def test_self_update_yt_dlp_exito(monkeypatch):
    monkeypatch.setattr(downloader.subprocess, "run", lambda *a, **k: _ResultadoProceso(0))
    assert downloader.self_update_yt_dlp("yt-dlp.exe") is True


def test_self_update_yt_dlp_codigo_no_cero(monkeypatch):
    monkeypatch.setattr(downloader.subprocess, "run", lambda *a, **k: _ResultadoProceso(1))
    assert downloader.self_update_yt_dlp("yt-dlp.exe") is False


def test_self_update_yt_dlp_no_explota_sin_red(monkeypatch):
    def _falla(*a, **k):
        raise downloader.subprocess.TimeoutExpired(cmd="yt-dlp.exe -U", timeout=25)

    monkeypatch.setattr(downloader.subprocess, "run", _falla)
    assert downloader.self_update_yt_dlp("yt-dlp.exe") is False


# ── DownloadWorker (sin arrancar un proceso real) ───────────────────────────

def test_construir_comando_video_incluye_merge_mp4():
    worker = downloader.DownloadWorker("https://x/video", "D:/Descargas", as_mp3=False)
    cmd = worker._construir_comando("yt-dlp.exe", "salida.txt")
    assert "--merge-output-format" in cmd
    assert "mp4" in cmd
    assert "--extract-audio" not in cmd


def test_construir_comando_audio_incluye_extract_audio_mp3():
    worker = downloader.DownloadWorker("https://x/audio", "D:/Descargas", as_mp3=True)
    cmd = worker._construir_comando("yt-dlp.exe", "salida.txt")
    assert "--extract-audio" in cmd
    assert "mp3" in cmd


def test_cancel_sin_proceso_no_explota():
    worker = downloader.DownloadWorker("https://x", "D:/Descargas", as_mp3=False)
    worker.cancel()
    assert worker._cancelado is True


def test_emitir_progreso_calcula_fraccion_y_texto():
    worker = downloader.DownloadWorker("https://x", "D:/Descargas", as_mp3=False)
    capturado = []
    worker.progress.connect(lambda frac, texto: capturado.append((frac, texto)))

    worker._emitir_progreso("500|1000|NA|102400|30")

    frac, texto = capturado[0]
    assert frac == 0.5
    assert "50%" in texto
    assert "100 KB/s" in texto


def test_emitir_progreso_ignora_payload_incompleto():
    worker = downloader.DownloadWorker("https://x", "D:/Descargas", as_mp3=False)
    capturado = []
    worker.progress.connect(lambda frac, texto: capturado.append((frac, texto)))

    worker._emitir_progreso("solo|dos")

    assert capturado == []


def test_leer_ruta_final_devuelve_la_ultima_ruta_existente(tmp_path):
    archivo_real = tmp_path / "cancion.mp3"
    archivo_real.write_bytes(b"x")
    archivo_txt = tmp_path / "salida.txt"
    archivo_txt.write_text(f"D:/no/existe.mp3\n{archivo_real}\n")

    ruta = downloader.DownloadWorker._leer_ruta_final(str(archivo_txt))
    assert ruta == str(archivo_real)


def test_leer_ruta_final_none_si_no_hay_archivo_de_salida():
    assert downloader.DownloadWorker._leer_ruta_final("D:/no/existe.txt") is None

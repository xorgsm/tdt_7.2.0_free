"""
Pruebas de core/torrent_client.py: no dependen del paquete libtorrent real
ni de red -- se sustituye el módulo torrent_client.lt entero por un doble
de prueba minimalista (mismo espíritu que el mock de requests.post en la
versión anterior de este archivo, adaptado a que ahora libtorrent es una
librería en proceso y no un servicio RPC).
"""
from types import SimpleNamespace

import pytest

from core import torrent_client
from core.torrent_client import TorrentClient, TorrentInfo


# ── dobles de prueba para el módulo libtorrent ──────────────────────────────

class _FakeTorrentStatusEnum:
    """Sustituye a lt.torrent_status como contenedor de constantes de
    estado -- valores simples y comparables, el código real solo hace
    comparaciones de igualdad/pertenencia, nunca asume el tipo exacto."""
    allocating = "allocating"
    checking_files = "checking_files"
    checking_resume_data = "checking_resume_data"
    downloading = "downloading"
    downloading_metadata = "downloading_metadata"
    finished = "finished"
    queued_for_checking = "queued_for_checking"
    seeding = "seeding"


def _fake_status(
    state="downloading", paused=False, errc=None, error="",
    download_rate=0, upload_rate=0, num_peers=0,
    total_wanted=0, total_wanted_done=0, progress=0.0, name="",
):
    return SimpleNamespace(
        state=state, paused=paused, errc=errc, error=error,
        download_rate=download_rate, upload_rate=upload_rate, num_peers=num_peers,
        total_wanted=total_wanted, total_wanted_done=total_wanted_done,
        progress=progress, name=name,
    )


class _FakeHandle:
    def __init__(self, status, valid=True):
        self._status = status
        self._valid = valid
        self.paused_calls = 0
        self.resumed_calls = 0

    def is_valid(self):
        return self._valid

    def status(self):
        return self._status

    def pause(self):
        self.paused_calls += 1

    def resume(self):
        self.resumed_calls += 1


class _FakeSession:
    delete_files = "DELETE_FILES_FLAG"

    def __init__(self, settings=None):
        self.settings = settings
        self.added = []
        self.removed = []

    def add_torrent(self, params):
        self.added.append(params)
        return params.handle

    def remove_torrent(self, handle, flags):
        self.removed.append((handle, flags))


class _FakeParams:
    def __init__(self, name="", handle=None):
        self.name = name
        self.trackers = []
        self.save_path = None
        self.ti = None
        self.handle = handle or _FakeHandle(_fake_status())


class _FakeLT:
    """Doble del módulo libtorrent completo."""
    torrent_status = _FakeTorrentStatusEnum

    def __init__(self):
        self.session = _FakeSession
        self._magnet_result = None
        self._magnet_error = None
        self._torrent_info_error = None

    def parse_magnet_uri(self, uri):
        if self._magnet_error:
            raise self._magnet_error
        return self._magnet_result or _FakeParams()

    def torrent_info(self, path):
        if self._torrent_info_error:
            raise self._torrent_info_error
        return SimpleNamespace(path=path)

    def add_torrent_params(self):
        return _FakeParams()


@pytest.fixture
def fake_lt(monkeypatch):
    fake = _FakeLT()
    monkeypatch.setattr(torrent_client, "lt", fake)
    monkeypatch.setattr(torrent_client, "LIBTORRENT_IMPORT_ERROR", "")
    return fake


def _conectado(fake_lt) -> TorrentClient:
    client = TorrentClient()
    assert client.conectar() is None
    return client


# ── paquete_disponible / __init__ ───────────────────────────────────────────

def test_paquete_disponible_refleja_si_libtorrent_se_pudo_importar(monkeypatch):
    monkeypatch.setattr(torrent_client, "lt", object())
    assert torrent_client.paquete_disponible() is True

    monkeypatch.setattr(torrent_client, "lt", None)
    assert torrent_client.paquete_disponible() is False


def test_init_ignora_argumentos_de_clientes_anteriores():
    # Firmas antiguas (qBittorrent, luego aria2): host/port/username/etc.
    # -- deben aceptarse sin romper, aunque ya no se usen.
    client = TorrentClient("127.0.0.1", 8080, username="a", password="b")
    assert client.conectado is False


# ── conectado / conectar ────────────────────────────────────────────────────

def test_conectado_es_false_antes_de_conectar():
    assert TorrentClient().conectado is False


def test_conectar_falla_si_libtorrent_no_se_pudo_importar(monkeypatch):
    monkeypatch.setattr(torrent_client, "lt", None)
    monkeypatch.setattr(torrent_client, "LIBTORRENT_IMPORT_ERROR", "No module named 'libtorrent'")
    error = TorrentClient().conectar()
    assert error is not None
    assert "libtorrent" in error


def test_conectar_ok_crea_sesion(fake_lt):
    client = TorrentClient()
    assert client.conectar() is None
    assert client.conectado is True


def test_conectar_dos_veces_no_crea_dos_sesiones(fake_lt):
    client = TorrentClient()
    client.conectar()
    sesion_original = client._session
    assert client.conectar() is None
    assert client._session is sesion_original


def test_conectar_falla_si_la_sesion_lanza_excepcion(fake_lt, monkeypatch):
    def _sesion_rota(settings=None):
        raise RuntimeError("no se pudo abrir el socket de escucha")

    monkeypatch.setattr(fake_lt, "session", _sesion_rota)
    client = TorrentClient()
    error = client.conectar()
    assert error is not None
    assert client.conectado is False


# ── anadir ───────────────────────────────────────────────────────────────────

def test_anadir_falla_si_no_esta_conectado():
    error = TorrentClient().anadir("magnet:?xt=urn:btih:abc", "D:/Descargas")
    assert error == "El motor de torrents no está en marcha."


def test_anadir_magnet_guarda_handle_con_token_propio(fake_lt):
    client = _conectado(fake_lt)
    error = client.anadir("magnet:?xt=urn:btih:abc", "D:/Descargas")
    assert error is None
    assert len(client._handles) == 1
    token = next(iter(client._handles))
    assert len(token) == 16  # secrets.token_hex(8)


def test_anadir_magnet_fija_save_path_y_suma_trackers_publicos(fake_lt):
    params = _FakeParams(name="")
    params.trackers = ["udp://tracker.propio.example:1337/announce"]
    fake_lt._magnet_result = params

    client = _conectado(fake_lt)
    client.anadir("magnet:?xt=urn:btih:abc", "D:/Descargas/Serie")

    assert params.save_path == "D:/Descargas/Serie"
    assert "udp://tracker.propio.example:1337/announce" in params.trackers
    for tr in torrent_client._TRACKERS_PUBLICOS:
        assert tr in params.trackers


def test_anadir_magnet_invalido_devuelve_error_sin_reventar(fake_lt):
    fake_lt._magnet_error = RuntimeError("magnet no válido")
    client = _conectado(fake_lt)
    error = client.anadir("magnet:?xt=urn:btih:roto", "D:/Descargas")
    assert error is not None
    assert client._handles == {}


def test_anadir_archivo_torrent_usa_torrent_info(fake_lt):
    client = _conectado(fake_lt)
    error = client.anadir("C:/descargas/pelicula.torrent", "D:/Descargas")
    assert error is None
    assert len(client._handles) == 1


def test_anadir_archivo_torrent_invalido_devuelve_error(fake_lt):
    fake_lt._torrent_info_error = RuntimeError("archivo .torrent corrupto")
    client = _conectado(fake_lt)
    error = client.anadir("C:/descargas/roto.torrent", "D:/Descargas")
    assert error is not None
    assert client._handles == {}


def test_anadir_si_session_add_torrent_rechaza_devuelve_error(fake_lt, monkeypatch):
    client = _conectado(fake_lt)

    def _rechaza(params):
        raise RuntimeError("torrent duplicado")

    monkeypatch.setattr(client._session, "add_torrent", _rechaza)
    error = client.anadir("magnet:?xt=urn:btih:abc", "D:/Descargas")
    assert error is not None
    assert client._handles == {}


# ── listar ───────────────────────────────────────────────────────────────────

def test_listar_vacio_si_no_esta_conectado():
    assert TorrentClient().listar() == []


def test_listar_construye_torrentinfo_desde_el_status(fake_lt):
    client = _conectado(fake_lt)
    status = _fake_status(
        state=_FakeTorrentStatusEnum.downloading, name="Mi Torrent",
        total_wanted=1000, total_wanted_done=250,
        download_rate=100, upload_rate=10, num_peers=3,
    )
    client._handles["tok1"] = _FakeHandle(status)

    resultado = client.listar()
    assert len(resultado) == 1
    info = resultado[0]
    assert isinstance(info, TorrentInfo)
    assert info.hash == "tok1"
    assert info.name == "Mi Torrent"
    assert info.progress == 0.25
    assert info.state == "downloading"
    assert info.dlspeed == 100
    assert info.upspeed == 10
    assert info.peers == 3
    assert info.eta == 7  # (1000-250)/100 = 7.5 -> int trunca a 7


def test_listar_usa_nombre_pendiente_hasta_que_llegan_metadatos(fake_lt):
    client = _conectado(fake_lt)
    sin_nombre = _fake_status(state=_FakeTorrentStatusEnum.downloading_metadata, name="")
    client._handles["tok1"] = _FakeHandle(sin_nombre)
    client._nombres_pendientes["tok1"] = "Nombre del magnet"

    info = client.listar()[0]
    assert info.name == "Nombre del magnet"

    # En cuanto el status ya trae nombre real, se usa ese y se limpia el
    # provisional.
    con_nombre = _fake_status(state=_FakeTorrentStatusEnum.downloading, name="Nombre Real")
    client._handles["tok1"] = _FakeHandle(con_nombre)
    info2 = client.listar()[0]
    assert info2.name == "Nombre Real"
    assert "tok1" not in client._nombres_pendientes


def test_listar_ignora_handles_invalidos(fake_lt):
    client = _conectado(fake_lt)
    client._handles["tok1"] = _FakeHandle(_fake_status(), valid=False)
    assert client.listar() == []


def test_listar_eta_menos_uno_sin_velocidad(fake_lt):
    client = _conectado(fake_lt)
    status = _fake_status(
        state=_FakeTorrentStatusEnum.downloading, total_wanted=1000,
        total_wanted_done=500, download_rate=0,
    )
    client._handles["tok1"] = _FakeHandle(status)
    assert client.listar()[0].eta == -1


# ── pausar / reanudar ───────────────────────────────────────────────────────

def test_pausar_reanudar_llaman_al_handle_si_es_valido(fake_lt):
    client = _conectado(fake_lt)
    handle = _FakeHandle(_fake_status())
    client._handles["tok1"] = handle

    client.pausar("tok1")
    client.reanudar("tok1")
    assert handle.paused_calls == 1
    assert handle.resumed_calls == 1


def test_pausar_reanudar_con_token_desconocido_no_revienta(fake_lt):
    client = _conectado(fake_lt)
    client.pausar("no-existe")
    client.reanudar("no-existe")


def test_pausar_con_handle_invalido_no_llama_pause(fake_lt):
    client = _conectado(fake_lt)
    handle = _FakeHandle(_fake_status(), valid=False)
    client._handles["tok1"] = handle
    client.pausar("tok1")
    assert handle.paused_calls == 0


# ── eliminar ─────────────────────────────────────────────────────────────────

def test_eliminar_sin_borrar_archivos_pasa_flags_cero(fake_lt):
    client = _conectado(fake_lt)
    handle = _FakeHandle(_fake_status())
    client._handles["tok1"] = handle
    client._nombres_pendientes["tok1"] = "x"

    client.eliminar("tok1", borrar_archivos=False)

    assert client._session.removed == [(handle, 0)]
    assert "tok1" not in client._handles
    assert "tok1" not in client._nombres_pendientes


def test_eliminar_borrando_archivos_usa_el_flag_delete_files(fake_lt):
    client = _conectado(fake_lt)
    handle = _FakeHandle(_fake_status())
    client._handles["tok1"] = handle

    client.eliminar("tok1", borrar_archivos=True)

    assert client._session.removed == [(handle, "DELETE_FILES_FLAG")]


def test_eliminar_token_desconocido_no_revienta(fake_lt):
    client = _conectado(fake_lt)
    client.eliminar("no-existe")
    assert client._session.removed == []


# ── cerrar ───────────────────────────────────────────────────────────────────

def test_cerrar_no_hace_nada_si_nunca_se_conecto():
    # No debe reventar aunque no haya sesión ni handles.
    TorrentClient().cerrar()


def test_cerrar_libera_sesion_y_handles(fake_lt):
    client = _conectado(fake_lt)
    client._handles["tok1"] = _FakeHandle(_fake_status())
    client.cerrar()
    assert client.conectado is False
    assert client._handles == {}


# ── _estado_legible (traducción de estados) ─────────────────────────────────

def test_estado_error_tiene_prioridad_sobre_el_resto(fake_lt):
    status = _fake_status(
        state=_FakeTorrentStatusEnum.downloading,
        errc=SimpleNamespace(value=lambda: 1, message=lambda: "disco lleno"),
    )
    assert torrent_client._estado_legible(status) == "error"


@pytest.mark.parametrize("estado_lt,esperado", [
    (_FakeTorrentStatusEnum.checking_files, "checkingDL"),
    (_FakeTorrentStatusEnum.checking_resume_data, "checkingDL"),
    (_FakeTorrentStatusEnum.queued_for_checking, "checkingDL"),
    (_FakeTorrentStatusEnum.downloading_metadata, "metaDL"),
    (_FakeTorrentStatusEnum.allocating, "queuedDL"),
])
def test_estados_intermedios_antes_de_descargar(fake_lt, estado_lt, esperado):
    status = _fake_status(state=estado_lt)
    assert torrent_client._estado_legible(status) == esperado


def test_estado_descargando_activo(fake_lt):
    status = _fake_status(
        state=_FakeTorrentStatusEnum.downloading, download_rate=50, num_peers=2,
    )
    assert torrent_client._estado_legible(status) == "downloading"


def test_estado_descargando_pausado(fake_lt):
    status = _fake_status(state=_FakeTorrentStatusEnum.downloading, paused=True)
    assert torrent_client._estado_legible(status) == "pausedDL"


def test_estado_descargando_estancado_sin_pares_ni_velocidad(fake_lt):
    status = _fake_status(
        state=_FakeTorrentStatusEnum.downloading, download_rate=0, num_peers=0,
    )
    assert torrent_client._estado_legible(status) == "stalledDL"


def test_estado_terminado_compartiendo(fake_lt):
    status = _fake_status(
        state=_FakeTorrentStatusEnum.seeding, upload_rate=20, num_peers=1,
    )
    assert torrent_client._estado_legible(status) == "uploading"


def test_estado_terminado_pausado(fake_lt):
    status = _fake_status(state=_FakeTorrentStatusEnum.finished, paused=True)
    assert torrent_client._estado_legible(status) == "pausedUP"


def test_estado_terminado_estancado_sin_pares_ni_subida(fake_lt):
    status = _fake_status(
        state=_FakeTorrentStatusEnum.finished, upload_rate=0, num_peers=0,
    )
    assert torrent_client._estado_legible(status) == "stalledUP"

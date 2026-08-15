"""
Pruebas de core/torrent_client.py: no dependen de aria2c.exe real ni de
red -- se sustituye requests.post (mismo patrón que test_updater.py) y
no se llega a arrancar el subproceso salvo cuando la propia prueba lo
controla explícitamente.
"""
from core import torrent_client
from core.torrent_client import TorrentClient, TorrentInfo


class _RespuestaFalsa:
    def __init__(self, data, status_ok=True):
        self._data = data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise torrent_client.requests.exceptions.HTTPError("500")

    def json(self):
        return self._data


# ── paquete_disponible / __init__ ───────────────────────────────────────────

def test_paquete_disponible_refleja_si_hay_aria2_empaquetado(monkeypatch):
    monkeypatch.setattr(torrent_client, "get_aria2_exe", lambda: "C:/app/aria2c.exe")
    assert torrent_client.paquete_disponible() is True

    monkeypatch.setattr(torrent_client, "get_aria2_exe", lambda: None)
    assert torrent_client.paquete_disponible() is False


def test_init_ignora_argumentos_del_cliente_anterior():
    # Firma antigua (qBittorrent): host/port/username/password -- deben
    # aceptarse sin romper, aunque ya no se usen.
    client = TorrentClient("127.0.0.1", 8080, username="a", password="b")
    assert client.conectado is False


# ── conectado / conectar ────────────────────────────────────────────────────

def test_conectado_es_false_antes_de_conectar():
    assert TorrentClient().conectado is False


def test_conectar_falla_si_no_hay_aria2_empaquetado(monkeypatch):
    monkeypatch.setattr(torrent_client, "get_aria2_exe", lambda: None)
    error = TorrentClient().conectar()
    assert error is not None
    assert "aria2c.exe" in error


# ── _rpc_call ────────────────────────────────────────────────────────────────

def test_rpc_call_devuelve_result_en_exito(monkeypatch):
    monkeypatch.setattr(
        torrent_client.requests, "post",
        lambda *a, **k: _RespuestaFalsa({"result": {"version": "1.36.0"}}),
    )
    resultado = TorrentClient()._rpc_call("aria2.getVersion")
    assert resultado == {"version": "1.36.0"}


def test_rpc_call_devuelve_none_si_aria2_responde_error(monkeypatch):
    monkeypatch.setattr(
        torrent_client.requests, "post",
        lambda *a, **k: _RespuestaFalsa({"error": {"code": 1, "message": "Unauthorized"}}),
    )
    assert TorrentClient()._rpc_call("aria2.pause", ["gid"]) is None


def test_rpc_call_devuelve_none_si_falla_la_red(monkeypatch):
    def _falla(*a, **k):
        raise torrent_client.requests.exceptions.ConnectionError("sin conexion")

    monkeypatch.setattr(torrent_client.requests, "post", _falla)
    assert TorrentClient()._rpc_call("aria2.getVersion") is None


def test_rpc_call_devuelve_none_si_json_es_invalido(monkeypatch):
    class _RespuestaRota(_RespuestaFalsa):
        def json(self):
            raise ValueError("no es json")

    monkeypatch.setattr(torrent_client.requests, "post", lambda *a, **k: _RespuestaRota({}))
    assert TorrentClient()._rpc_call("aria2.getVersion") is None


# ── anadir / listar sin conexión ────────────────────────────────────────────

def test_anadir_falla_si_no_esta_conectado():
    error = TorrentClient().anadir("magnet:?xt=urn:btih:abc", "D:/Descargas")
    assert error == "El motor de torrents no está en marcha."


def test_listar_vacio_si_no_esta_conectado():
    assert TorrentClient().listar() == []


# ── pausar / reanudar / eliminar delegan en _rpc_call ───────────────────────

def test_pausar_reanudar_eliminar_llaman_al_metodo_rpc_correcto(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        TorrentClient, "_rpc_call",
        lambda self, method, params=None, timeout=5: llamadas.append((method, params)),
    )
    client = TorrentClient()
    client.pausar("gid1")
    client.reanudar("gid1")
    client.eliminar("gid1")

    assert ("aria2.pause", ["gid1"]) in llamadas
    assert ("aria2.unpause", ["gid1"]) in llamadas
    assert ("aria2.remove", ["gid1"]) in llamadas
    assert ("aria2.removeDownloadResult", ["gid1"]) in llamadas


# ── cerrar ───────────────────────────────────────────────────────────────────

def test_cerrar_no_hace_nada_si_nunca_se_conecto():
    # No debe intentar hablar por RPC ni tocar un proceso que no existe.
    TorrentClient().cerrar()


# ── _parse_torrent (función pura) ───────────────────────────────────────────

def test_parse_torrent_calcula_progreso_y_traduce_estado():
    info = TorrentClient._parse_torrent({
        "gid": "abc123", "totalLength": "1000", "completedLength": "250",
        "downloadSpeed": "100", "uploadSpeed": "10", "connections": "3",
        "status": "active", "bittorrent": {"info": {"name": "Mi Torrent"}},
    })
    assert isinstance(info, TorrentInfo)
    assert info.hash == "abc123"
    assert info.name == "Mi Torrent"
    assert info.progress == 0.25
    assert info.state == "downloading"  # active -> downloading
    assert info.dlspeed == 100
    assert info.upspeed == 10
    assert info.peers == 3
    assert info.eta == 7  # (1000-250)/100 = 7.5 -> int trunca a 7


def test_parse_torrent_usa_nombre_de_archivo_si_no_hay_info_bittorrent():
    info = TorrentClient._parse_torrent({
        "gid": "x", "totalLength": "0", "completedLength": "0",
        "files": [{"path": "D:/Descargas/pelicula.mkv"}],
        "status": "waiting",
    })
    assert info.name == "pelicula.mkv"
    assert info.state == "queuedDL"  # waiting -> queuedDL


def test_parse_torrent_nombre_por_defecto_sin_info_ni_archivos():
    info = TorrentClient._parse_torrent({"gid": "x", "status": "paused"})
    assert info.name == "(obteniendo nombre…)"
    assert info.state == "pausedDL"


def test_parse_torrent_progreso_cero_sin_total():
    info = TorrentClient._parse_torrent({"gid": "x", "totalLength": "0", "status": "error"})
    assert info.progress == 0.0
    assert info.state == "error"


def test_parse_torrent_eta_menos_uno_sin_velocidad():
    info = TorrentClient._parse_torrent({
        "gid": "x", "totalLength": "1000", "completedLength": "500",
        "downloadSpeed": "0", "status": "paused",
    })
    assert info.eta == -1

"""
Pruebas de core/dlna_caster.py: construcción de peticiones SOAP/UPnP
(funciones puras), descripción de dispositivos y descubrimiento con la
red sustituida, y las rutas de error de DLNASession -- sin depender de
un televisor real en la red.
"""
import pytest

from core import dlna_caster
from core.dlna_caster import DLNADevice, DLNASession, _describe_device, _escape_xml, _soap_body, discover_dlna_devices


# ── _escape_xml / _soap_body (funciones puras) ──────────────────────────────

def test_escape_xml_escapa_caracteres_especiales():
    assert _escape_xml('Ana & "Bea" <hola>') == "Ana &amp; &quot;Bea&quot; &lt;hola&gt;"


def test_soap_body_incluye_accion_y_argumentos():
    cuerpo = _soap_body("Play", {"Speed": "1"})
    assert "<u:Play " in cuerpo
    assert "<Speed>1</Speed>" in cuerpo
    assert "<InstanceID>0</InstanceID>" in cuerpo


# ── _describe_device ─────────────────────────────────────────────────────────

_XML_DISPOSITIVO_VALIDO = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>TV Salón</friendlyName>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/AVTransport/control</controlURL>
      </service>
    </serviceList>
  </device>
</root>"""


class _RespuestaHttpFalsa:
    def __init__(self, content: bytes, ok: bool = True):
        self.content = content
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise dlna_caster.requests.exceptions.HTTPError("500")


def test_describe_device_extrae_nombre_y_control_url(monkeypatch):
    monkeypatch.setattr(
        dlna_caster.requests, "get",
        lambda *a, **k: _RespuestaHttpFalsa(_XML_DISPOSITIVO_VALIDO.encode("utf-8")),
    )
    device = _describe_device("http://192.168.1.50:1400/desc.xml")
    assert device is not None
    assert device.name == "TV Salón"
    assert device.control_url == "http://192.168.1.50:1400/AVTransport/control"


def test_describe_device_devuelve_none_sin_avtransport(monkeypatch):
    xml_sin_avtransport = _XML_DISPOSITIVO_VALIDO.replace("AVTransport", "RenderingControl")
    monkeypatch.setattr(
        dlna_caster.requests, "get",
        lambda *a, **k: _RespuestaHttpFalsa(xml_sin_avtransport.encode("utf-8")),
    )
    assert _describe_device("http://192.168.1.50:1400/desc.xml") is None


def test_describe_device_devuelve_none_si_falla_la_peticion(monkeypatch):
    def _falla(*a, **k):
        raise dlna_caster.requests.exceptions.ConnectionError("sin respuesta")

    monkeypatch.setattr(dlna_caster.requests, "get", _falla)
    assert _describe_device("http://192.168.1.50:1400/desc.xml") is None


def test_describe_device_devuelve_none_con_xml_invalido(monkeypatch):
    monkeypatch.setattr(
        dlna_caster.requests, "get", lambda *a, **k: _RespuestaHttpFalsa(b"esto no es xml")
    )
    assert _describe_device("http://192.168.1.50:1400/desc.xml") is None


# ── discover_dlna_devices ────────────────────────────────────────────────────

def test_discover_dlna_devices_filtra_duplicados_y_nulos(monkeypatch):
    ubicaciones = ["http://a/desc.xml", "http://a/desc.xml", "http://b/desc.xml"]
    monkeypatch.setattr(dlna_caster, "_ssdp_search", lambda timeout=4.0: ubicaciones)

    llamadas = []

    def _describe_falso(location):
        llamadas.append(location)
        if location == "http://b/desc.xml":
            return None  # este dispositivo no expone AVTransport
        return DLNADevice(name="TV A", location=location, control_url="http://a/control")

    monkeypatch.setattr(dlna_caster, "_describe_device", _describe_falso)

    dispositivos = discover_dlna_devices()

    assert llamadas == ["http://a/desc.xml", "http://b/desc.xml"]  # "a" solo se describe una vez
    assert len(dispositivos) == 1
    assert dispositivos[0].name == "TV A"


# ── DLNASession ──────────────────────────────────────────────────────────────

def test_cast_url_sin_dispositivo_lanza_runtimeerror():
    session = DLNASession()
    with pytest.raises(RuntimeError):
        session.cast_url("http://stream", "audio/mp3")


def test_cast_url_exito_llama_seturi_y_play(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        dlna_caster, "_soap_action",
        lambda control_url, action, args, timeout=6.0: llamadas.append((action, args)),
    )
    session = DLNASession()
    session.connect(DLNADevice(name="TV", location="loc", control_url="http://tv/control"))

    session.cast_url("http://stream.mp3", "audio/mp3", title="Radio X")

    acciones = [a for a, _ in llamadas]
    assert acciones == ["SetAVTransportURI", "Play"]


def test_cast_url_fallo_de_red_se_convierte_en_runtimeerror_amigable(monkeypatch):
    def _falla(*a, **k):
        raise dlna_caster.requests.exceptions.ConnectionError("rechazado")

    monkeypatch.setattr(dlna_caster, "_soap_action", _falla)
    session = DLNASession()
    session.connect(DLNADevice(name="TV", location="loc", control_url="http://tv/control"))

    with pytest.raises(RuntimeError, match="rechazó el envío"):
        session.cast_url("http://stream.mp3", "audio/mp3")


def test_stop_sin_dispositivo_no_hace_nada():
    DLNASession().stop()  # no debe explotar sin device conectado


def test_stop_con_dispositivo_llama_a_stop_soap(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        dlna_caster, "_soap_action",
        lambda control_url, action, args, timeout=6.0: llamadas.append(action),
    )
    session = DLNASession()
    session.connect(DLNADevice(name="TV", location="loc", control_url="http://tv/control"))
    session.stop()

    assert llamadas == ["Stop"]


def test_stop_no_explota_si_falla_la_peticion(monkeypatch):
    def _falla(*a, **k):
        raise dlna_caster.requests.exceptions.ConnectionError("sin respuesta")

    monkeypatch.setattr(dlna_caster, "_soap_action", _falla)
    session = DLNASession()
    session.connect(DLNADevice(name="TV", location="loc", control_url="http://tv/control"))
    session.stop()  # no debe propagar la excepción

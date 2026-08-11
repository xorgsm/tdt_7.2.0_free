"""
Envío de contenido (canal/emisora en directo, o archivo local) a un
televisor con soporte DLNA/UPnP ("renderizador de medios"), como
alternativa a Chromecast para las TV que no tienen Google Cast integrado
(la mayoría de Smart TV de fábrica sí traen DLNA, aunque no sean Google
Cast: Samsung, LG, Sony, Panasonic...).

Sin dependencias nuevas: descubrimiento por SSDP (multicast UDP, solo
socket de la librería estándar) y control por SOAP/UPnP AVTransport
(HTTP normal vía requests, que ya usa el proyecto en varios sitios).

Aviso importante: a diferencia de Chromecast, muchos renderizadores DLNA
de fábrica no soportan HLS adaptativo (.m3u8, el formato con el que
emiten casi todos los canales TDT) — solo reproducción progresiva simple
(MP4, MP3, AAC). Radio y archivos locales/descargados funcionan de forma
fiable; TV en directo depende del modelo concreto de televisor.

Coder By X@R
"""
import re
import socket
import time
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from PySide6.QtCore import QThread, Signal

from core.logger import get_logger

log = get_logger(__name__)

_SSDP_ADDR = ("239.255.255.250", 1900)
_SSDP_MX = 3
_SSDP_ST = "urn:schemas-upnp-org:service:AVTransport:1"

_NS_DEVICE = "{urn:schemas-upnp-org:device-1-0}"
_NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_AVT = "urn:schemas-upnp-org:service:AVTransport:1"


class DLNADevice:
    """Datos mínimos de un renderizador DLNA descubierto por SSDP."""

    def __init__(self, name: str, location: str, control_url: str):
        self.name = name
        self.location = location
        self.control_url = control_url


def _ssdp_search(timeout: float = 4.0) -> list:
    """Manda un M-SEARCH SSDP y devuelve las URL LOCATION de quien responde."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {_SSDP_ADDR[0]}:{_SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {_SSDP_MX}\r\n"
        f"ST: {_SSDP_ST}\r\n"
        "\r\n"
    ).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    locations = []
    try:
        sock.sendto(msg, _SSDP_ADDR)
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            texto = data.decode("utf-8", errors="ignore")
            match = re.search(r"(?im)^location:\s*(.+)\r?$", texto)
            if match:
                url = match.group(1).strip()
                if url not in locations:
                    locations.append(url)
    except OSError:
        log.exception("Fallo al enviar la búsqueda SSDP")
    finally:
        sock.close()
    return locations


def _describe_device(location: str):
    """Descarga el XML de descripción del dispositivo y extrae nombre + controlURL de AVTransport."""
    try:
        resp = requests.get(location, timeout=4)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        log.debug("No se pudo leer la descripción del dispositivo en %s", location)
        return None

    ns = _NS_DEVICE
    friendly = root.findtext(f".//{ns}friendlyName") or "TV DLNA"

    control_url = None
    for service in root.iter(f"{ns}service"):
        service_type = service.findtext(f"{ns}serviceType") or ""
        if "AVTransport" in service_type:
            control_path = service.findtext(f"{ns}controlURL")
            if control_path:
                control_url = urljoin(location, control_path)
            break

    if not control_url:
        return None
    return DLNADevice(name=friendly, location=location, control_url=control_url)


def discover_dlna_devices(timeout: float = 4.0) -> list:
    """Busca renderizadores DLNA en la red local y devuelve los que exponen AVTransport."""
    devices = []
    vistos = set()
    for location in _ssdp_search(timeout=timeout):
        if location in vistos:
            continue
        vistos.add(location)
        device = _describe_device(location)
        if device is not None:
            devices.append(device)
    return devices


class DLNADiscoveryWorker(QThread):
    """Busca TV/renderizadores DLNA en la red local (Wi-Fi/LAN), en un hilo aparte."""
    found = Signal(list)  # lista de nombres amigables (str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = []

    def run(self):
        try:
            self.devices = discover_dlna_devices(timeout=4.0)
        except Exception:
            log.exception("Fallo al buscar dispositivos DLNA en la red")
            self.devices = []
        self.found.emit([d.name for d in self.devices])

    def device_by_name(self, name: str):
        for d in self.devices:
            if d.name == name:
                return d
        return None


def _escape_xml(texto: str) -> str:
    return (
        texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_DIDL_TEMPLATE = (
    '&lt;DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"&gt;'
    '&lt;item id="0" parentID="-1" restricted="1"&gt;'
    '&lt;dc:title&gt;{title}&lt;/dc:title&gt;'
    '&lt;upnp:class&gt;object.item.{clase}Item&lt;/upnp:class&gt;'
    '&lt;res protocolInfo="http-get:*:{content_type}:*"&gt;{url}&lt;/res&gt;'
    '&lt;/item&gt;&lt;/DIDL-Lite&gt;'
)


def _soap_body(action: str, args: dict) -> str:
    args_xml = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{_NS_SOAP}" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{_NS_AVT}">'
        f"<InstanceID>0</InstanceID>{args_xml}"
        f"</u:{action}>"
        "</s:Body></s:Envelope>"
    )


def _soap_action(control_url: str, action: str, args: dict, timeout: float = 6.0):
    body = _soap_body(action, args)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{_NS_AVT}#{action}"',
    }
    resp = requests.post(control_url, data=body.encode("utf-8"), headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


class DLNASession:
    """Conexión activa con un renderizador DLNA y control de qué se le envía."""

    def __init__(self):
        self.device = None
        self.device_name = None
        # Import diferido: evita un ciclo core.caster <-> core.dlna_caster si en
        # el futuro caster.py necesitara importar algo de este módulo.
        from core.caster import LocalFileServer
        self.file_server = LocalFileServer()

    def connect(self, device: DLNADevice):
        self.device = device
        self.device_name = device.name

    def cast_url(self, url: str, content_type: str, title: str = ""):
        if self.device is None:
            raise RuntimeError("No hay ningún dispositivo conectado.")
        clase = "audio" if content_type.startswith("audio") else "video"
        metadata = _DIDL_TEMPLATE.format(
            title=_escape_xml(title or "Coder By X@R"),
            clase=clase,
            content_type=_escape_xml(content_type),
            url=_escape_xml(url),
        )
        try:
            _soap_action(
                self.device.control_url, "SetAVTransportURI",
                {"CurrentURI": _escape_xml(url), "CurrentURIMetaData": metadata},
            )
            _soap_action(self.device.control_url, "Play", {"Speed": "1"})
        except requests.RequestException as exc:
            raise RuntimeError(
                "El televisor rechazó el envío. Algunos modelos DLNA no admiten "
                "este formato de vídeo en directo (HLS); con radio o archivos "
                "descargados suele funcionar sin problema."
            ) from exc

    def cast_local_file(self, filepath: str, title: str = ""):
        url, content_type = self.file_server.serve(filepath)
        self.cast_url(url, content_type, title=title)

    def stop(self):
        if self.device is not None:
            try:
                _soap_action(self.device.control_url, "Stop", {})
            except requests.RequestException:
                log.exception(
                    "Fallo al detener la reproducción en el dispositivo %s", self.device_name
                )
        self.file_server.stop()

    def disconnect(self):
        self.stop()
        self.device = None
        self.device_name = None

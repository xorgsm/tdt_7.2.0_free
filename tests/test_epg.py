"""
Pruebas de core/epg.py: el fallo real que se reportó ("la guía nunca
funciona") era que el tvg-id de la lista M3U (con sufijo de calidad de
iptv-org, p. ej. "La1.es@SD") nunca coincidía tal cual con el id/
display-name que trae la fuente EPG (p. ej. "La 1 HD" con <display-name>
"La 1"), así que channel_key() y el indexado de fetch_epg() por esa
clave normalizada son lo que se comprueba aquí.
"""
from datetime import datetime, timedelta

from core.epg import channel_key, fetch_epg, get_now_next


def test_channel_key_quita_sufijo_de_calidad_de_iptv_org():
    assert channel_key("La1.es@SD") == "la1"
    assert channel_key("Antena3Internacional.es@HD") == "antena3internacional"


def test_channel_key_normaliza_espacios_puntos_y_mayusculas():
    assert channel_key("La 1") == "la1"
    assert channel_key("antena 3.es") == "antena3"
    assert channel_key("Telemadrid.es") == "telemadrid"


def test_channel_key_vacio():
    assert channel_key("") == ""
    assert channel_key(None) == ""


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S") + " +0000"


def _xmltv_ejemplo() -> str:
    # Ventana de 2 horas alrededor de "ahora" -- así get_now_next() (que usa
    # datetime.now() internamente, sin parámetro inyectable) encuentra el
    # programa como "en emisión" sea cual sea el momento real en que se
    # ejecute la prueba.
    ahora = datetime.now()
    inicio = _fmt(ahora - timedelta(hours=1))
    fin = _fmt(ahora + timedelta(hours=1))
    fin_anterior = _fmt(ahora - timedelta(hours=1))
    inicio_anterior = _fmt(ahora - timedelta(hours=2))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="La 1 HD">
    <display-name>La 1</display-name>
    <display-name>La 1 HD</display-name>
  </channel>
  <channel id="antena 3.es">
    <display-name>antena 3.es</display-name>
  </channel>
  <programme start="{inicio}" stop="{fin}" channel="La 1 HD">
    <title>Telediario</title>
  </programme>
  <programme start="{inicio_anterior}" stop="{fin_anterior}" channel="antena 3.es">
    <title>Programa anterior</title>
  </programme>
</tv>
"""


class _RespuestaFalsa:
    def __init__(self, contenido: str):
        self.content = contenido.encode("utf-8")

    def raise_for_status(self):
        pass


def test_fetch_epg_indexa_por_clave_normalizada_no_por_id_crudo(monkeypatch):
    monkeypatch.setattr("core.epg.requests.get", lambda *a, **k: _RespuestaFalsa(_xmltv_ejemplo()))

    guide = fetch_epg("https://fake-epg")

    # El id crudo del XMLTV ("La 1 HD") no debe ser una clave del guide:
    # todo tiene que pasar por channel_key().
    assert "La 1 HD" not in guide
    assert "la1hd" in guide  # channel_key(id crudo)
    assert "la1" in guide    # channel_key(del <display-name> "La 1")


def test_get_now_next_encuentra_el_canal_por_tvg_id_de_iptv_org(monkeypatch):
    """Este es el caso real reportado: la lista de canales trae
    tvg-id="La1.es@SD" (formato iptv-org), y la guía EPG solo conoce el
    canal como "La 1 HD" / "La 1" -- antes de channel_key(), esto nunca
    cruzaba nada."""
    monkeypatch.setattr("core.epg.requests.get", lambda *a, **k: _RespuestaFalsa(_xmltv_ejemplo()))
    guide = fetch_epg("https://fake-epg")

    current, _ = get_now_next(guide, "La1.es@SD")
    assert current is not None
    assert current.title == "Telediario"


def test_get_now_next_sin_coincidencia_devuelve_none_none():
    current, upcoming = get_now_next({}, "CanalQueNoExiste.es@SD")
    assert current is None
    assert upcoming is None

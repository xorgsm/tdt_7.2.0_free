"""
Pruebas de core/channels.py: parseo de listas M3U y deduplicado de
canales. Son funciones puras (sin red ni disco), ideales para cubrir con
tests unitarios rápidos.
"""
from core.channels import (
    Channel,
    add_custom_channels,
    dedupe_channels,
    filter_hidden,
    hide_channels,
    load_custom_channels,
    load_hidden_channel_names,
    parse_m3u,
    playlist_url_for,
    record_channel_failure,
    remove_custom_channels,
    reset_channel_failures,
    unhide_channels,
)

M3U_EJEMPLO = """#EXTM3U
#EXTINF:-1 tvg-id="la1.es" tvg-logo="http://logo/la1.png" group-title="Generalistas",La 1
http://stream/la1.m3u8
#EXTINF:-1 tvg-id="la2.es" group-title="Generalistas",La 2
http://stream/la2.m3u8
"""


def test_parse_m3u_extrae_campos():
    canales = parse_m3u(M3U_EJEMPLO)
    assert len(canales) == 2

    la1 = canales[0]
    assert la1.name == "La 1"
    assert la1.url == "http://stream/la1.m3u8"
    assert la1.logo == "http://logo/la1.png"
    assert la1.group == "Generalistas"
    assert la1.tvg_id == "la1.es"


def test_parse_m3u_ignora_extinf_sin_url_siguiente():
    texto = "#EXTM3U\n#EXTINF:-1,Canal huérfano\n#EXTINF:-1,Canal bueno\nhttp://x/y.m3u8\n"
    canales = parse_m3u(texto)
    assert len(canales) == 1
    assert canales[0].name == "Canal bueno"


def test_parse_m3u_dedupe_por_nombre_case_insensitive():
    texto = (
        "#EXTM3U\n"
        "#EXTINF:-1,La 1\nhttp://a\n"
        "#EXTINF:-1,  la 1  \nhttp://b\n"
    )
    canales = parse_m3u(texto)
    assert len(canales) == 1
    assert canales[0].url == "http://a"  # se queda con la primera aparición


def test_dedupe_channels_preserva_orden_y_primera_aparicion():
    canales = [
        Channel(name="A", url="1"),
        Channel(name="B", url="2"),
        Channel(name="a", url="3"),
    ]
    resultado = dedupe_channels(canales)
    assert [c.url for c in resultado] == ["1", "2"]


def test_playlist_url_for_usa_codigo_pais_en_minuscula():
    assert playlist_url_for("FR") == "https://iptv-org.github.io/iptv/countries/fr.m3u"


def test_playlist_url_for_sin_codigo_usa_es():
    assert playlist_url_for("") == "https://iptv-org.github.io/iptv/countries/es.m3u"


# ── remove_custom_channels (borrado por lotes, ver ManageChannelsDialog) ────

def test_remove_custom_channels_borra_solo_los_pedidos():
    add_custom_channels([
        Channel(name="A", url="http://a"),
        Channel(name="B", url="http://b"),
        Channel(name="C", url="http://c"),
    ])

    borrados = remove_custom_channels({"A", "C"})

    assert borrados == 2
    restantes = load_custom_channels()
    assert [c.name for c in restantes] == ["B"]


def test_remove_custom_channels_cuenta_solo_los_que_existian():
    add_custom_channels([Channel(name="A", url="http://a")])

    borrados = remove_custom_channels({"A", "NoExiste"})

    assert borrados == 1
    assert load_custom_channels() == []


def test_remove_custom_channels_lista_vacia_no_toca_nada():
    add_custom_channels([Channel(name="A", url="http://a")])

    assert remove_custom_channels([]) == 0
    assert len(load_custom_channels()) == 1


def test_remove_custom_channels_sin_archivo_previo_no_falla():
    assert remove_custom_channels({"Lo que sea"}) == 0


# ── ocultar/restaurar canales de la lista pública (ver ManageChannelsDialog) ─

def test_hide_channels_añade_y_devuelve_cuantos_son_nuevos():
    añadidos = hide_channels({"La 1", "La 2"})

    assert añadidos == 2
    assert load_hidden_channel_names() == {"La 1", "La 2"}


def test_hide_channels_no_cuenta_los_ya_ocultos():
    hide_channels({"La 1"})

    añadidos = hide_channels({"La 1", "La 2"})

    assert añadidos == 1
    assert load_hidden_channel_names() == {"La 1", "La 2"}


def test_hide_channels_lista_vacia_no_toca_nada():
    assert hide_channels([]) == 0
    assert load_hidden_channel_names() == set()


def test_unhide_channels_quita_y_devuelve_cuantos_quito():
    hide_channels({"La 1", "La 2", "La 3"})

    quitados = unhide_channels({"La 1", "La 3", "NoEstaba"})

    assert quitados == 2
    assert load_hidden_channel_names() == {"La 2"}


def test_unhide_channels_sin_archivo_previo_no_falla():
    assert unhide_channels({"Lo que sea"}) == 0


def test_filter_hidden_quita_los_ocultos_y_deja_el_resto():
    canales = [
        Channel(name="La 1", url="http://a"),
        Channel(name="La 2", url="http://b"),
        Channel(name="La 3", url="http://c"),
    ]
    hide_channels({"La 2"})

    visibles = filter_hidden(canales)

    assert [c.name for c in visibles] == ["La 1", "La 3"]


def test_filter_hidden_sin_ocultos_devuelve_la_misma_lista():
    canales = [Channel(name="La 1", url="http://a")]

    assert filter_hidden(canales) == canales


# ── fallos consecutivos (aviso de auto-ocultar, ver PlaybackController) ─────

def test_record_channel_failure_acumula_por_nombre():
    assert record_channel_failure("La 1") == 1
    assert record_channel_failure("La 1") == 2
    assert record_channel_failure("La 1") == 3


def test_record_channel_failure_cuenta_aparte_por_canal():
    record_channel_failure("La 1")
    record_channel_failure("La 1")
    assert record_channel_failure("La 2") == 1


def test_record_channel_failure_nombre_vacio_no_cuenta():
    assert record_channel_failure("") == 0


def test_reset_channel_failures_pone_el_contador_a_cero():
    record_channel_failure("La 1")
    record_channel_failure("La 1")

    reset_channel_failures("La 1")

    assert record_channel_failure("La 1") == 1


def test_reset_channel_failures_sin_fallos_previos_no_falla():
    reset_channel_failures("Canal que nunca falló")

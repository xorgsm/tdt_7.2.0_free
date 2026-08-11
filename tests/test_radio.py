"""
Pruebas de core/radio.py: solo la parte de persistencia de emisoras
personalizadas (fetch_radio_stations hace peticiones de red reales, fuera
de alcance de un test unitario). remove_custom_stations() es la versión
por lotes usada por ManageChannelsDialog -- ver test_channels.py para el
equivalente de TV, misma lógica.
"""
from core.radio import (
    Station,
    add_custom_stations,
    filter_hidden,
    hide_stations,
    load_custom_stations,
    load_hidden_station_names,
    record_channel_failure,
    remove_custom_stations,
    reset_channel_failures,
    unhide_stations,
)


def test_add_custom_stations_persiste_varias_de_golpe():
    add_custom_stations([
        Station(name="A", url="http://a"),
        Station(name="B", url="http://b"),
    ])
    assert [s.name for s in load_custom_stations()] == ["A", "B"]


def test_remove_custom_stations_borra_solo_las_pedidas():
    add_custom_stations([
        Station(name="A", url="http://a"),
        Station(name="B", url="http://b"),
        Station(name="C", url="http://c"),
    ])

    borradas = remove_custom_stations({"A", "C"})

    assert borradas == 2
    assert [s.name for s in load_custom_stations()] == ["B"]


def test_remove_custom_stations_cuenta_solo_las_que_existian():
    add_custom_stations([Station(name="A", url="http://a")])

    borradas = remove_custom_stations({"A", "NoExiste"})

    assert borradas == 1
    assert load_custom_stations() == []


def test_remove_custom_stations_lista_vacia_no_toca_nada():
    add_custom_stations([Station(name="A", url="http://a")])

    assert remove_custom_stations([]) == 0
    assert len(load_custom_stations()) == 1


def test_remove_custom_stations_sin_archivo_previo_no_falla():
    assert remove_custom_stations({"Lo que sea"}) == 0


# ── ocultar/restaurar emisoras de la lista pública (ver ManageChannelsDialog,
# misma lógica que hide_channels/unhide_channels/filter_hidden en
# test_channels.py) ──────────────────────────────────────────────────────────

def test_hide_stations_añade_y_devuelve_cuantas_son_nuevas():
    añadidas = hide_stations({"RNE", "Cadena SER"})

    assert añadidas == 2
    assert load_hidden_station_names() == {"RNE", "Cadena SER"}


def test_hide_stations_no_cuenta_las_ya_ocultas():
    hide_stations({"RNE"})

    añadidas = hide_stations({"RNE", "Cadena SER"})

    assert añadidas == 1
    assert load_hidden_station_names() == {"RNE", "Cadena SER"}


def test_hide_stations_lista_vacia_no_toca_nada():
    assert hide_stations([]) == 0
    assert load_hidden_station_names() == set()


def test_unhide_stations_quita_y_devuelve_cuantas_quito():
    hide_stations({"RNE", "Cadena SER", "Los 40"})

    quitadas = unhide_stations({"RNE", "Los 40", "NoEstaba"})

    assert quitadas == 2
    assert load_hidden_station_names() == {"Cadena SER"}


def test_unhide_stations_sin_archivo_previo_no_falla():
    assert unhide_stations({"Lo que sea"}) == 0


def test_filter_hidden_quita_las_ocultas_y_deja_el_resto():
    emisoras = [
        Station(name="RNE", url="http://a"),
        Station(name="Cadena SER", url="http://b"),
        Station(name="Los 40", url="http://c"),
    ]
    hide_stations({"Cadena SER"})

    visibles = filter_hidden(emisoras)

    assert [s.name for s in visibles] == ["RNE", "Los 40"]


def test_filter_hidden_sin_ocultas_devuelve_la_misma_lista():
    emisoras = [Station(name="RNE", url="http://a")]

    assert filter_hidden(emisoras) == emisoras


# ── fallos consecutivos (aviso de auto-ocultar, ver PlaybackController) ─────

def test_record_channel_failure_acumula_por_nombre():
    assert record_channel_failure("RNE") == 1
    assert record_channel_failure("RNE") == 2
    assert record_channel_failure("RNE") == 3


def test_record_channel_failure_cuenta_aparte_por_emisora():
    record_channel_failure("RNE")
    record_channel_failure("RNE")
    assert record_channel_failure("Cadena SER") == 1


def test_record_channel_failure_nombre_vacio_no_cuenta():
    assert record_channel_failure("") == 0


def test_reset_channel_failures_pone_el_contador_a_cero():
    record_channel_failure("RNE")
    record_channel_failure("RNE")

    reset_channel_failures("RNE")

    assert record_channel_failure("RNE") == 1


def test_reset_channel_failures_sin_fallos_previos_no_falla():
    reset_channel_failures("Emisora que nunca falló")

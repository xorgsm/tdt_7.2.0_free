"""
Pruebas de core/history.py: add_entry() debe llevar la cuenta de
reproducciones (play_count) en vez de reiniciarla cada vez que un canal
vuelve a reproducirse, y top_played() debe ordenar por esa cuenta.
"""
from core import history


def test_add_entry_nueva_empieza_en_uno():
    history.add_entry("tv", "La 1", "http://stream1")
    entradas = history.load_history()
    assert entradas[0]["play_count"] == 1


def test_add_entry_repetida_incrementa_play_count():
    history.add_entry("tv", "La 1", "http://stream1")
    history.add_entry("radio", "Otra", "http://stream2")
    history.add_entry("tv", "La 1", "http://stream1")

    entradas = history.load_history()
    la1 = next(e for e in entradas if e["name"] == "La 1")
    assert la1["play_count"] == 2
    # Repetir la reproducción también la vuelve a subir al principio.
    assert entradas[0]["name"] == "La 1"


def test_top_played_ordena_por_play_count():
    history.add_entry("tv", "La 1", "http://a")
    history.add_entry("radio", "RNE", "http://b")
    history.add_entry("tv", "La 1", "http://a")
    history.add_entry("tv", "La 1", "http://a")

    top = history.top_played(limit=5)
    assert top[0]["name"] == "La 1"
    assert top[0]["play_count"] == 3


def test_top_played_respeta_limit():
    for i in range(5):
        history.add_entry("tv", f"Canal {i}", f"http://c{i}")

    assert len(history.top_played(limit=3)) == 3


def test_clear_history_vacia_para_stats():
    history.add_entry("tv", "La 1", "http://a")
    history.clear_history()
    assert history.top_played() == []

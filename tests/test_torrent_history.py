"""
Pruebas de core/torrent_history.py: mismo patrón que core/history.py
pero para torrents completados -- add_entry() no debe duplicar una
entrada ya existente (mismo nombre+ruta), solo subirla al principio.
"""
import json

from core import torrent_history


def test_add_entry_nueva_aparece_primero():
    torrent_history.add_entry("Peli.mkv", "D:/Descargas/Peli.mkv", size=1234)
    entradas = torrent_history.load_history()
    assert entradas[0]["name"] == "Peli.mkv"
    assert entradas[0]["path"] == "D:/Descargas/Peli.mkv"


def test_add_entry_repetida_no_duplica_se_mueve_arriba():
    torrent_history.add_entry("A.mkv", "D:/A.mkv")
    torrent_history.add_entry("B.mkv", "D:/B.mkv")
    torrent_history.add_entry("A.mkv", "D:/A.mkv")

    entradas = torrent_history.load_history()
    assert len(entradas) == 2
    assert entradas[0]["name"] == "A.mkv"


def test_add_entry_sin_nombre_o_ruta_no_se_guarda():
    resultado = torrent_history.add_entry("", "D:/algo.mkv")
    assert resultado == []
    assert torrent_history.load_history() == []


def test_has_entry():
    torrent_history.add_entry("A.mkv", "D:/A.mkv")
    assert torrent_history.has_entry("A.mkv", "D:/A.mkv") is True
    assert torrent_history.has_entry("B.mkv", "D:/B.mkv") is False


def test_remove_entry():
    torrent_history.add_entry("A.mkv", "D:/A.mkv")
    torrent_history.add_entry("B.mkv", "D:/B.mkv")

    restante = torrent_history.remove_entry("A.mkv", "D:/A.mkv")

    assert len(restante) == 1
    assert restante[0]["name"] == "B.mkv"


def test_clear_history():
    torrent_history.add_entry("A.mkv", "D:/A.mkv")
    torrent_history.clear_history()
    assert torrent_history.load_history() == []


def test_load_history_ignora_json_corrupto():
    # Simula un archivo corrupto en disco -- no debe explotar, debe
    # devolver lista vacía en vez de propagar el error de parseo.
    path = torrent_history._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("esto no es json valido", encoding="utf-8")

    assert torrent_history.load_history() == []


def test_load_history_ignora_entradas_mal_formadas():
    path = torrent_history._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([
        {"name": "Bien.mkv", "path": "D:/Bien.mkv"},
        {"name": "Sin ruta"},
        "no es un dict",
    ]), encoding="utf-8")

    entradas = torrent_history.load_history()
    assert len(entradas) == 1
    assert entradas[0]["name"] == "Bien.mkv"

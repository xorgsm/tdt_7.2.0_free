"""
Pruebas de core/favorites.py: alternar, carpetas y el nuevo reorder()
usado por el arrastrar-y-soltar de la pestaña de Favoritos.
"""
from core.favorites import (
    delete_folder,
    get_folders,
    is_favorite,
    load_favorites,
    remove_favorite,
    rename_folder,
    reorder,
    set_favorite_folder,
    toggle_favorite,
)


def test_toggle_favorite_añade_y_quita():
    favs = toggle_favorite("tv", "La 1", url="http://x", logo="http://logo")
    assert is_favorite(favs, "tv", "La 1")
    favs = toggle_favorite("tv", "La 1")
    assert not is_favorite(favs, "tv", "La 1")


def test_toggle_favorite_persiste_en_disco():
    toggle_favorite("tv", "La 1", url="http://x")
    assert is_favorite(load_favorites(), "tv", "La 1")


def test_remove_favorite_no_falla_si_no_existe():
    assert remove_favorite("tv", "No existe") == []


def test_folders_set_rename_delete():
    toggle_favorite("tv", "La 1", url="http://x")
    toggle_favorite("radio", "Cadena Ser", url="http://y")
    set_favorite_folder("tv", "La 1", "Generalistas")
    assert get_folders() == ["Generalistas"]

    rename_folder("Generalistas", "Nacionales")
    assert get_folders() == ["Nacionales"]

    delete_folder("Nacionales")
    favs = load_favorites()
    assert all(not f.get("folder") for f in favs)


def test_reorder_persiste_el_orden_dado():
    toggle_favorite("tv", "A", url="http://a")
    toggle_favorite("tv", "B", url="http://b")
    favs = load_favorites()
    # toggle_favorite inserta al principio, así que ahora mismo está [B, A].
    invertido = list(reversed(favs))

    reorder(invertido)

    recargado = load_favorites()
    assert [f["name"] for f in recargado] == [f["name"] for f in invertido]

from core.channels import Channel
from core.radio import Station
from core.universal_search import normalize, search_catalog


def test_normalize_ignores_case_accents_and_extra_spaces():
    assert normalize("  RádiO   Española ") == "radio espanola"


def test_search_matches_metadata_and_prioritizes_favorites():
    tv = Channel("Canal Uno", "https://tv.example/one", group="Noticias", tvg_id="canal.uno")
    radio = Station("Radio Uno", "https://radio.example/one", tags="noticias, actualidad")

    results = search_catalog(
        "noticias",
        [tv],
        [radio],
        favorites=[{"type": "radio", "name": "Radio Uno"}],
    )

    assert [result["name"] for result in results] == ["Radio Uno", "Canal Uno"]


def test_search_keeps_recent_item_missing_from_catalog():
    results = search_catalog(
        "clasica",
        history=[{
            "type": "radio", "name": "Radio Clásica", "url": "https://radio.example/classic",
        }],
    )

    assert len(results) == 1
    assert results[0]["kind"] == "radio"
    assert results[0]["subtitle"] == "Historial reciente"
    assert results[0]["payload"]["url"] == "https://radio.example/classic"


def test_search_deduplicates_catalog_and_history_by_kind_and_name():
    station = Station("Radio Uno", "https://radio.example/current")
    results = search_catalog(
        "radio uno",
        radio_stations=[station],
        history=[{
            "type": "radio", "name": "RADIO UNO", "url": "https://radio.example/old",
        }],
    )

    assert len(results) == 1
    assert results[0]["payload"] is station

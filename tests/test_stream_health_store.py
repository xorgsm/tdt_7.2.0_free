import json

import pytest

from core.stream_health_store import (
    StreamHealthStore, derive_health_status, matches_health_filter, summarize_health,
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"status": "ok", "latency_ms": 200}, "stable"),
        ({"status": "ok", "latency_ms": 1500}, "slow"),
        ({"status": "error", "http_status": 0}, "down"),
        ({"status": "ok", "http_status": 403}, "restricted"),
        ({"status": "restricted", "latency_ms": 10}, "restricted"),
    ],
)
def test_derive_health_status(result, expected):
    assert derive_health_status(result) == expected


@pytest.mark.parametrize(
    ("status", "filter_key", "expected"),
    [
        # "all" acepta cualquier estado, incluido "sin diagnosticar" (None).
        ("stable", "all", True),
        (None, "all", True),
        ("stable", "stable", True),
        ("slow", "stable", False),
        (None, "stable", False),
        ("slow", "issues", True),
        ("down", "issues", True),
        ("restricted", "issues", True),
        ("stable", "issues", False),
        (None, "issues", False),
        (None, "unchecked", True),
        ("", "unchecked", True),
        ("stable", "unchecked", False),
        # Un filtro desconocido no debe ocultar nada por accidente.
        ("down", "no-existe", True),
    ],
)
def test_matches_health_filter(status, filter_key, expected):
    assert matches_health_filter(status, filter_key) is expected


def test_record_result_persists_history_by_kind_and_url(tmp_path):
    path = tmp_path / "stream_health.json"
    store = StreamHealthStore(path, max_history=2)

    first = store.record_result(
        "tv", "https://example.test/live", {"status": "ok", "latency_ms": 80},
        checked_at="2026-08-22T10:00:00+00:00",
    )
    second = store.record_result(
        "tv", "https://example.test/live", {"status": "error", "error": "offline"},
        checked_at="2026-08-22T11:00:00+00:00",
    )

    assert first["status"] == "stable"
    assert second["status"] == "down"
    restored = StreamHealthStore(path).get("tv", "https://example.test/live")
    assert restored["checked_at"] == "2026-08-22T11:00:00+00:00"
    assert [event["status"] for event in restored["history"]] == ["down", "stable"]
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_list_filters_by_kind_and_orders_newest_first(tmp_path):
    store = StreamHealthStore(tmp_path / "health.json")
    store.record_result("tv", "https://tv.test", {"status": "ok"}, checked_at="2026-01-01T00:00:00+00:00")
    store.record_result("radio", "https://radio.test", {"status": "ok"}, checked_at="2026-01-02T00:00:00+00:00")

    assert [item["url"] for item in store.list()] == ["https://radio.test", "https://tv.test"]
    assert [item["kind"] for item in store.list("tv")] == ["tv"]


def test_clear_removes_selected_stream_or_all_states(tmp_path):
    store = StreamHealthStore(tmp_path / "health.json")
    store.record_results([
        {"kind": "tv", "url": "https://one.test", "status": "ok"},
        {"kind": "tv", "url": "https://two.test", "status": "error"},
        {"kind": "radio", "url": "https://one.test", "status": "ok"},
    ])

    assert store.clear("tv", "https://one.test") == 1
    assert store.get("tv", "https://one.test") is None
    assert store.clear("tv") == 1
    assert store.clear() == 1
    assert store.list() == []


def test_store_tolerates_invalid_file_and_rejects_incomplete_identity(tmp_path):
    path = tmp_path / "health.json"
    path.write_text('{"streams": ["bad", {"kind": "tv"}]}', encoding="utf-8")
    store = StreamHealthStore(path)

    assert store.list() == []
    with pytest.raises(ValueError):
        store.record_result("", "https://stream.test", {"status": "ok"})
    with pytest.raises(ValueError):
        store.clear(url="https://stream.test")


def test_summarize_health_accepts_saved_and_raw_diagnostic_results():
    assert summarize_health([
        {"status": "stable"},
        {"status": "ok", "latency_ms": 2_000},
        {"status": "error"},
        {"status": "restricted"},
    ]) == {"total": 4, "stable": 1, "slow": 1, "down": 1, "restricted": 1}

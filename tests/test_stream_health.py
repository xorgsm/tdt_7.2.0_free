import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from core.stream_health import diagnose_catalog, probe_stream, safe_csv_cell, summarize_results


class FakeResponse:
    def __init__(self, status_code=200, url="https://stream.example/final", content_type="audio/aac; charset=utf-8"):
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.closed = False

    def close(self):
        self.closed = True


def test_probe_stream_records_redirect_response_and_content_type():
    response = FakeResponse()
    received = {}

    def fake_get(*args, **kwargs):
        received.update(kwargs)
        return response

    result = probe_stream({"url": "https://stream.example/original"}, request_get=fake_get)

    assert result["status"] == "ok"
    assert result["final_url"] == "https://stream.example/final"
    assert result["content_type"] == "audio/aac"
    assert response.closed is True
    assert received["stream"] is True
    assert received["allow_redirects"] is True


def test_probe_stream_classifies_restricted_response():
    result = probe_stream(
        {"url": "https://stream.example/restricted"},
        request_get=lambda *args, **kwargs: FakeResponse(status_code=403),
    )

    assert result["status"] == "restricted"
    assert result["error"] == "Acceso restringido por el servidor"


def test_probe_stream_returns_error_for_request_exception():
    def failing_get(*args, **kwargs):
        raise requests.ConnectionError("offline")

    result = probe_stream({"url": "https://stream.example/offline"}, request_get=failing_get)

    assert result["status"] == "error"
    assert "offline" in result["error"]


def test_diagnose_catalog_skips_empty_urls_and_reports_progress():
    progress = []

    def probe(entry):
        return {**entry, "status": "ok"}

    results = diagnose_catalog(
        [{"name": "Valido", "url": "https://stream.example"}, {"name": "Vacio", "url": ""}],
        progress=lambda result, completed, total: progress.append((result["name"], completed, total)),
        probe=probe,
    )

    assert [result["name"] for result in results] == ["Valido"]
    assert progress == [("Valido", 1, 1)]


def test_diagnose_catalog_stops_collecting_after_cancellation():
    cancelled = threading.Event()

    def probe(entry):
        cancelled.set()
        return {**entry, "status": "ok"}

    results = diagnose_catalog(
        [{"name": "Uno", "url": "https://one.example"}, {"name": "Dos", "url": "https://two.example"}],
        cancel_event=cancelled,
        probe=probe,
    )

    assert results == []


def test_diagnose_catalog_does_not_wait_for_in_flight_request_after_cancellation(monkeypatch):
    """Cancelar debe devolver el control aunque una solicitud siga bloqueada."""
    cancelled = threading.Event()
    release_probe = threading.Event()
    blocked_probe_started = threading.Event()
    real_shutdown = ThreadPoolExecutor.shutdown
    shutdown_calls = []

    def fake_shutdown(self, wait=True, *, cancel_futures=False):
        shutdown_calls.append((wait, cancel_futures))
        return real_shutdown(self, wait=wait, cancel_futures=cancel_futures)

    def probe(entry):
        if entry["name"] == "Cancelar":
            assert blocked_probe_started.wait(timeout=1)
            cancelled.set()
            return {**entry, "status": "ok"}
        blocked_probe_started.set()
        release_probe.wait(timeout=2)
        return {**entry, "status": "ok"}

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", fake_shutdown)
    try:
        assert diagnose_catalog(
            [
                {"name": "Bloqueado", "url": "https://one.example"},
                {"name": "Cancelar", "url": "https://two.example"},
            ],
            cancel_event=cancelled,
            probe=probe,
        ) == []
        assert blocked_probe_started.is_set()
        assert shutdown_calls == [(False, True)]
    finally:
        release_probe.set()


def test_summary_and_csv_cells_handle_problem_results_and_formula_prefixes():
    summary = summarize_results([
        {"kind": "tv", "status": "ok"},
        {"kind": "tv", "status": "error"},
        {"kind": "radio", "status": "restricted"},
    ])

    assert summary == {"total": 3, "ok": 1, "problems": 2, "tv_problems": 1, "radio_problems": 1}
    assert safe_csv_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert safe_csv_cell("Canal seguro") == "Canal seguro"

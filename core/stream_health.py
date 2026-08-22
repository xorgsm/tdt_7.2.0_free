"""Diagnóstico concurrente y cancelable de URLs de TV y radio."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import requests


def safe_csv_cell(value: object) -> str:
    """Evita que nombres remotos se interpreten como fórmulas al abrir el CSV."""
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def summarize_results(results: Iterable[dict]) -> dict:
    summary = {"total": 0, "ok": 0, "problems": 0, "tv_problems": 0, "radio_problems": 0}
    for result in results:
        summary["total"] += 1
        if result.get("status") == "ok":
            summary["ok"] += 1
            continue
        summary["problems"] += 1
        key = "tv_problems" if result.get("kind") == "tv" else "radio_problems"
        summary[key] += 1
    return summary


def probe_stream(entry: dict, timeout: float = 6.0, request_get=requests.get) -> dict:
    started = time.monotonic()
    result = {**entry, "status": "error", "http_status": 0, "latency_ms": 0,
              "content_type": "", "final_url": entry.get("url", ""), "error": ""}
    try:
        response = request_get(
            entry.get("url", ""), timeout=timeout, stream=True, allow_redirects=True,
            headers={"User-Agent": "TDT-Radio-VIP/7.5.6", "Range": "bytes=0-1023"},
        )
        result["latency_ms"] = round((time.monotonic() - started) * 1000)
        result["http_status"] = response.status_code
        result["content_type"] = response.headers.get("Content-Type", "").split(";", 1)[0]
        result["final_url"] = response.url
        if 200 <= response.status_code < 400:
            result["status"] = "ok"
        elif response.status_code in (401, 403):
            result["status"] = "restricted"
            result["error"] = "Acceso restringido por el servidor"
        else:
            result["error"] = f"Respuesta HTTP {response.status_code}"
        response.close()
    except requests.RequestException as exc:
        result["latency_ms"] = round((time.monotonic() - started) * 1000)
        result["error"] = str(exc)
    return result


def diagnose_catalog(
    entries: Iterable[dict], progress: Callable[[dict, int, int], None] | None = None,
    cancel_event: threading.Event | None = None, max_workers: int = 12,
    probe: Callable[[dict], dict] = probe_stream,
) -> list[dict]:
    items = [entry for entry in entries if entry.get("url")]
    total = len(items)
    if not items:
        return []
    cancel_event = cancel_event or threading.Event()
    results: list[dict] = []
    executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, total)))
    futures = {executor.submit(probe, entry): entry for entry in items}
    try:
        for future in as_completed(futures):
            if cancel_event.is_set():
                break
            try:
                result = future.result()
            except Exception as exc:  # un probe personalizado no debe romper el lote
                result = {**futures[future], "status": "error", "http_status": 0,
                          "latency_ms": 0, "content_type": "", "final_url": "",
                          "error": str(exc)}
            results.append(result)
            if progress:
                progress(result, len(results), total)
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        # No esperamos las peticiones que ya estaban en vuelo: ``requests``
        # no ofrece una cancelación segura de una conexión bloqueada y esperar
        # aquí hacía que el botón Cancelar pareciera no responder hasta el
        # timeout. Las tareas pendientes se descartan y las que ya están
        # ejecutándose terminan solas sin volver a tocar la interfaz.
        executor.shutdown(wait=False, cancel_futures=True)
    return results

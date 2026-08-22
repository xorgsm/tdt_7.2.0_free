"""Almacén persistente del estado de salud de canales y emisoras.

El diagnóstico produce resultados efímeros. Este módulo conserva una pequeña
historia por ``(tipo, URL)`` para que la interfaz pueda mostrar el estado del
stream sin volver a comprobarlo al abrir una lista.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from core.config import get_profile_data_dir
from core.json_store import read_json, write_json_atomic


HEALTH_FILE = "stream_health.json"
MAX_HISTORY_PER_STREAM = 20
SLOW_LATENCY_MS = 1_500
HealthStatus = Literal["stable", "slow", "down", "restricted"]

# Claves del filtro por estado de las listas de TV/Radio (ver el desplegable
# "health_filter" de ui/main_window.py). "issues" agrupa todo lo que no es
# estable pero sí se ha medido; "unchecked" son streams aún sin diagnóstico.
ISSUE_STATUSES = frozenset({"slow", "down", "restricted"})


def matches_health_filter(status: str | None, filter_key: str) -> bool:
    """¿Debe mostrarse un stream con ``status`` bajo el filtro ``filter_key``?

    ``status`` es el estado persistido del stream o ``None``/"" si nunca se
    ha diagnosticado. Un ``filter_key`` desconocido no oculta nada: ante un
    valor inesperado es preferible enseñar de más que hacer desaparecer
    canales sin explicación.
    """
    if filter_key == "stable":
        return status == "stable"
    if filter_key == "issues":
        return status in ISSUE_STATUSES
    if filter_key == "unchecked":
        return not status
    return True


def derive_health_status(
    result: Mapping[str, object], *, slow_latency_ms: int = SLOW_LATENCY_MS
) -> HealthStatus:
    """Clasifica un resultado de :func:`core.stream_health.probe_stream`.

    Las restricciones tienen precedencia sobre cualquier otro campo; una URL
    que devuelve 401/403 no debe confundirse con una caída temporal.
    """
    status = str(result.get("status", "")).lower()
    http_status = result.get("http_status", 0)
    if status == "restricted" or http_status in (401, 403):
        return "restricted"
    if status != "ok":
        return "down"
    try:
        latency_ms = int(result.get("latency_ms", 0) or 0)
    except (TypeError, ValueError):
        latency_ms = 0
    return "slow" if latency_ms >= slow_latency_ms else "stable"


class StreamHealthStore:
    """Guarda y consulta el historial de diagnósticos de un perfil.

    ``path`` permite inyectar una ruta temporal en pruebas. Sin ella, los
    datos se guardan junto al resto de datos del perfil activo.
    """

    def __init__(
        self, path: Path | None = None, *, max_history: int = MAX_HISTORY_PER_STREAM
    ) -> None:
        if max_history < 1:
            raise ValueError("max_history debe ser al menos 1")
        self.path = path or get_profile_data_dir() / HEALTH_FILE
        self.max_history = max_history

    def record_result(
        self,
        kind: str,
        url: str,
        result: Mapping[str, object],
        *,
        checked_at: str | None = None,
    ) -> dict:
        """Registra un resultado y devuelve el estado actualizado.

        ``kind`` normalmente es ``tv`` o ``radio``. Se conserva como texto
        para no perder compatibilidad con futuras fuentes de stream.
        """
        kind, url = self._validate_identity(kind, url)
        checked_at = checked_at or _utc_now()
        event = _event_from_result(result, checked_at)
        streams = self._load_streams()
        current = next(
            (stream for stream in streams if stream["kind"] == kind and stream["url"] == url),
            None,
        )
        if current is None:
            current = {"kind": kind, "url": url, "history": []}
            streams.append(current)

        history = current.setdefault("history", [])
        history.insert(0, event)
        del history[self.max_history :]
        current.update(event)
        current["history"] = history
        self._save_streams(streams)
        return _public_stream(current)

    def record_results(self, results: Iterable[Mapping[str, object]]) -> list[dict]:
        """Registra un lote de resultados válidos y devuelve sus estados."""
        recorded = []
        for result in results:
            kind = str(result.get("kind", ""))
            url = str(result.get("url", ""))
            if kind and url:
                recorded.append(self.record_result(kind, url, result))
        return recorded

    def get(self, kind: str, url: str) -> dict | None:
        """Devuelve el estado de un stream o ``None`` si no se ha medido."""
        kind, url = self._validate_identity(kind, url)
        for stream in self._load_streams():
            if stream["kind"] == kind and stream["url"] == url:
                return _public_stream(stream)
        return None

    def list(self, kind: str | None = None) -> list[dict]:
        """Lista estados, con los comprobados más recientemente primero."""
        streams = self._load_streams()
        if kind is not None:
            kind = kind.strip()
            streams = [stream for stream in streams if stream["kind"] == kind]
        return sorted(
            (_public_stream(stream) for stream in streams),
            key=lambda stream: stream["checked_at"],
            reverse=True,
        )

    def clear(self, kind: str | None = None, url: str | None = None) -> int:
        """Elimina estados y devuelve cuántos streams se han retirado."""
        if url is not None and kind is None:
            raise ValueError("kind es obligatorio al limpiar una URL concreta")
        if kind is not None:
            kind = kind.strip()
        if url is not None:
            url = url.strip()
        streams = self._load_streams()
        kept = [
            stream
            for stream in streams
            if not (kind is None or stream["kind"] == kind)
            or (url is not None and stream["url"] != url)
        ]
        removed = len(streams) - len(kept)
        if removed:
            self._save_streams(kept)
        return removed

    def _load_streams(self) -> list[dict]:
        data = read_json(self.path, {"streams": []})
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
            return []
        return [_normalise_stream(stream) for stream in data["streams"] if _is_stream(stream)]

    def _save_streams(self, streams: list[dict]) -> None:
        write_json_atomic(self.path, {"version": 1, "streams": streams}, indent=2)

    @staticmethod
    def _validate_identity(kind: str, url: str) -> tuple[str, str]:
        kind, url = kind.strip(), url.strip()
        if not kind or not url:
            raise ValueError("kind y url son obligatorios")
        return kind, url


# API funcional para la interfaz ------------------------------------------------
#
# La UI no necesita conocer archivos ni instanciar el almacén: estas funciones
# usan automáticamente la carpeta del perfil activo. La clase se mantiene
# pública para pruebas y para importación/exportación futura.

def record_results(results: Iterable[Mapping[str, object]]) -> list[dict]:
    """Persiste un lote de resultados del diagnóstico en el perfil activo."""
    return StreamHealthStore().record_results(results)


def get_status(kind: str, url: str) -> dict | None:
    """Devuelve el último estado persistido de un stream del perfil activo."""
    return StreamHealthStore().get(kind, url)


def summarize_health(entries: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Cuenta estados para mostrar el resumen del Centro de salud.

    Acepta tanto los estados devueltos por :func:`get_status`/``list`` como
    resultados crudos del diagnóstico, en cuyo caso se clasifican primero.
    """
    summary = {"total": 0, "stable": 0, "slow": 0, "down": 0, "restricted": 0}
    for entry in entries:
        status = str(entry.get("status", "")).lower()
        if status not in {"stable", "slow", "down", "restricted"}:
            status = derive_health_status(entry)
        summary["total"] += 1
        summary[status] += 1
    return summary


def clear_health(kind: str | None = None, url: str | None = None) -> int:
    """Borra estados del perfil activo; sin argumentos borra todo el historial."""
    return StreamHealthStore().clear(kind, url)


def _event_from_result(result: Mapping[str, object], checked_at: str) -> dict:
    return {
        "status": derive_health_status(result),
        "checked_at": checked_at,
        "latency_ms": _as_int(result.get("latency_ms", 0)),
        "http_status": _as_int(result.get("http_status", 0)),
        "error": str(result.get("error", "") or ""),
    }


def _is_stream(value: object) -> bool:
    return isinstance(value, dict) and bool(value.get("kind")) and bool(value.get("url"))


def _normalise_stream(stream: dict) -> dict:
    history = stream.get("history")
    history = history if isinstance(history, list) else []
    normalised_history = [event for event in history if isinstance(event, dict)]
    return {
        "kind": str(stream["kind"]),
        "url": str(stream["url"]),
        "status": str(stream.get("status", "down")),
        "checked_at": str(stream.get("checked_at", "")),
        "latency_ms": _as_int(stream.get("latency_ms", 0)),
        "http_status": _as_int(stream.get("http_status", 0)),
        "error": str(stream.get("error", "") or ""),
        "history": normalised_history,
    }


def _public_stream(stream: dict) -> dict:
    return {**stream, "history": [dict(event) for event in stream["history"]]}


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

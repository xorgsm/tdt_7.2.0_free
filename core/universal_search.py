"""Motor independiente de Qt para la búsqueda universal de la aplicación."""
from __future__ import annotations

import unicodedata
from typing import Iterable


def normalize(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    return " ".join("".join(ch for ch in value if not unicodedata.combining(ch)).split())


def _score(query: str, name: str, metadata: str, favorite: bool, recent: bool) -> int:
    tokens = query.split()
    searchable = f"{name} {metadata}".strip()
    if not tokens or not all(token in searchable for token in tokens):
        return -1
    score = 100
    if name == query:
        score += 1000
    elif name.startswith(query):
        score += 500
    elif query in name:
        score += 250
    score += sum(80 if name.startswith(token) else 30 if token in name else 5 for token in tokens)
    score += 60 if favorite else 0
    score += 25 if recent else 0
    return score


def search_catalog(
    query: str,
    tv_channels: Iterable = (),
    radio_stations: Iterable = (),
    favorites: Iterable[dict] = (),
    history: Iterable[dict] = (),
    limit: int = 40,
) -> list[dict]:
    """Busca por nombre, categoría, país, etiquetas y TVG ID, ordenando por relevancia."""
    query = normalize(query)
    if not query or limit <= 0:
        return []

    favorite_keys = {(f.get("type"), normalize(f.get("name"))) for f in favorites}
    recent_keys = {(e.get("type"), normalize(e.get("name"))) for e in history}
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, name: str, metadata: str, payload, subtitle: str):
        normalized_name = normalize(name)
        key = (kind, normalized_name)
        score = _score(query, normalized_name, normalize(metadata), key in favorite_keys, key in recent_keys)
        if score < 0 or key in seen:
            return
        seen.add(key)
        results.append({
            "kind": kind, "name": name, "subtitle": subtitle,
            "payload": payload, "score": score,
        })

    for channel in tv_channels:
        metadata = " ".join((channel.group, channel.tvg_id))
        add("tv", channel.name, metadata, channel, channel.group or "Televisión")
    for station in radio_stations:
        metadata = " ".join((station.tags, station.country, str(station.bitrate or "")))
        details = " · ".join(part for part in (station.country, station.tags) if part) or "Radio"
        add("radio", station.name, metadata, station, details)

    # Conserva entradas recientes que ya no estén en el catálogo descargado.
    for entry in history:
        kind = entry.get("type", "")
        if kind not in ("tv", "radio") or not entry.get("url"):
            continue
        add(kind, entry.get("name", ""), "historial reciente", entry, "Historial reciente")

    results.sort(key=lambda result: (-result["score"], normalize(result["name"])))
    return results[:limit]

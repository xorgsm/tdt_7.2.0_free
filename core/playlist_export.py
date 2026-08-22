"""Exportación segura de canales y emisoras a listas M3U compatibles."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path


def build_m3u(entries: Iterable[Mapping[str, object]]) -> str:
    """Devuelve una lista M3U UTF-8 a partir de entradas de TV o radio.

    Se ignoran entradas sin nombre o URL; los atributos conservan metadatos
    útiles para que al volver a importarla se recuperen logos, categorías y
    TVG ID cuando estén disponibles.
    """
    lines = ["#EXTM3U"]
    for entry in entries:
        name = str(entry.get("name", "") or "").strip()
        url = str(entry.get("url", "") or "").strip()
        if not name or not url:
            continue
        logo = str(entry.get("logo", "") or "").strip()
        group = str(entry.get("group", "") or entry.get("tags", "") or "").strip()
        tvg_id = str(entry.get("tvg_id", "") or "").strip()
        attrs = []
        if tvg_id:
            attrs.append(f'tvg-id="{_attribute(tvg_id)}"')
        if logo:
            attrs.append(f'tvg-logo="{_attribute(logo)}"')
        if group:
            attrs.append(f'group-title="{_attribute(group)}"')
        suffix = f" {' '.join(attrs)}" if attrs else ""
        lines.extend((f"#EXTINF:-1{suffix},{name}", url))
    return "\n".join(lines) + "\n"


def export_m3u(entries: Iterable[Mapping[str, object]], destination: str | Path) -> int:
    """Guarda una lista M3U y devuelve el número de streams exportados."""
    content = build_m3u(entries)
    Path(destination).write_text(content, encoding="utf-8", newline="\n")
    return sum(1 for line in content.splitlines() if line.startswith("#EXTINF:"))


def _attribute(value: str) -> str:
    return value.replace('"', "'").replace("\r", " ").replace("\n", " ")

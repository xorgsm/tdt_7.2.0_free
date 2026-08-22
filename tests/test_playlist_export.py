from core.playlist_export import build_m3u, export_m3u


def test_build_m3u_preserves_compatible_metadata_and_skips_incomplete_entries():
    playlist = build_m3u([
        {
            "name": "Canal \"Uno\"", "url": "https://tv.example/live.m3u8",
            "logo": "https://tv.example/logo.png", "group": "Noticias", "tvg_id": "canal.uno",
        },
        {"name": "Sin URL", "url": ""},
    ])

    assert playlist.startswith("#EXTM3U\n")
    assert 'tvg-id="canal.uno"' in playlist
    assert 'tvg-logo="https://tv.example/logo.png"' in playlist
    assert 'group-title="Noticias"' in playlist
    assert "Canal \"Uno\"" in playlist
    assert "Sin URL" not in playlist


def test_export_m3u_writes_utf8_playlist_and_returns_stream_count(tmp_path):
    destination = tmp_path / "mis_canales.m3u"
    count = export_m3u([
        {"name": "Radio Española", "url": "https://radio.example/live", "tags": "Música"},
    ], destination)

    assert count == 1
    assert "Radio Española" in destination.read_text(encoding="utf-8")

import json

from core import backup


def test_backup_preserves_stream_health_for_the_active_profile(tmp_path, monkeypatch):
    app_data = tmp_path / "app"
    profile_data = tmp_path / "profile"
    app_data.mkdir()
    profile_data.mkdir()
    health_path = profile_data / "stream_health.json"
    health = {"version": 1, "streams": [{"kind": "tv", "url": "https://stream.example", "history": []}]}
    health_path.write_text(json.dumps(health), encoding="utf-8")
    monkeypatch.setattr(backup, "get_app_data_dir", lambda: app_data)
    monkeypatch.setattr(backup, "get_profile_data_dir", lambda: profile_data)

    archive = tmp_path / "backup.json"
    backup.export_backup(str(archive))
    payload = json.loads(archive.read_text(encoding="utf-8"))

    assert payload["stream_health"] == health

    health_path.unlink()
    assert "stream_health" in backup.import_backup(str(archive))
    assert json.loads(health_path.read_text(encoding="utf-8")) == health

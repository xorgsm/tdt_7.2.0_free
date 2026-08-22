import os

from core.recording_library import list_recordings


def test_list_recordings_only_returns_supported_media_newest_first(tmp_path):
    old = tmp_path / "antigua.mp4"
    old.write_bytes(b"old")
    new = tmp_path / "radio.mka"
    new.write_bytes(b"newer")
    (tmp_path / "radio.log").write_text("ffmpeg", encoding="utf-8")
    (tmp_path / "nota.txt").write_text("no", encoding="utf-8")

    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    recordings = list_recordings(tmp_path)

    assert [item.path.name for item in recordings] == ["radio.mka", "antigua.mp4"]
    assert recordings[0].size == 5


def test_list_recordings_treats_missing_directory_as_empty(tmp_path):
    assert list_recordings(tmp_path / "missing") == []

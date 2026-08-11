from core import recorder


def test_start_no_fuerza_filtro_exclusivo_de_aac(tmp_path, monkeypatch):
    """Un stream E-AC-3 debe llegar a FFmpeg sin un filtro solo para AAC."""
    commands = []

    class _Process:
        pass

    monkeypatch.setattr(recorder, "get_ffmpeg_exe", lambda: "ffmpeg.exe")
    monkeypatch.setattr(
        recorder.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or _Process(),
    )
    recording = recorder.Recorder(str(tmp_path))

    try:
        recording.start("https://example.test/eac3.m3u8", "Canal E-AC-3")
    finally:
        if recording._log_fh:
            recording._log_fh.close()

    assert "-bsf:a" not in commands[0]
    assert "aac_adtstoasc" not in commands[0]

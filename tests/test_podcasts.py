from core import podcasts


class _ChunkedResponse:
    """Respuesta HTTP mínima con dos bloques para cancelar entre ambos."""

    headers = {"Content-Length": "12"}

    def __init__(self):
        self._chunks = iter((b"primer", b"segundo", b""))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return next(self._chunks)


def test_cancelar_descarga_elimina_el_archivo_incompleto(tmp_path, monkeypatch):
    """Evita que una cancelación deje un episodio aparentemente completo."""
    monkeypatch.setattr(
        podcasts.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _ChunkedResponse(),
    )
    episode = podcasts.Episode(
        title="Episodio de prueba",
        audio_url="https://example.test/audio.mp3",
    )
    worker = podcasts.EpisodeDownloadWorker(episode, str(tmp_path))
    failures = []
    worker.progress.connect(lambda *_args: worker.cancel())
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == ["__cancelled__"]
    assert not (tmp_path / "Episodio de prueba.mp3").exists()


def test_cancelar_descarga_conserva_un_episodio_existente(tmp_path, monkeypatch):
    """Una repetición cancelada no debe truncar la descarga anterior."""
    monkeypatch.setattr(
        podcasts.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _ChunkedResponse(),
    )
    destination = tmp_path / "Episodio de prueba.mp3"
    destination.write_bytes(b"episodio completo anterior")
    episode = podcasts.Episode(
        title="Episodio de prueba",
        audio_url="https://example.test/audio.mp3",
    )
    worker = podcasts.EpisodeDownloadWorker(episode, str(tmp_path))
    worker.progress.connect(lambda *_args: worker.cancel())

    worker.run()

    assert destination.read_bytes() == b"episodio completo anterior"
    assert not (tmp_path / "Episodio de prueba.mp3.part").exists()

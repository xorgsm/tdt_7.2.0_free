"""
Pruebas de la búsqueda multi-fuente de música (YouTube/SoundCloud/música
libre) en core/downloader.py: construcción del comando yt-dlp por fuente y
parseo de cada línea --dump-json a un resultado utilizable por la UI,
incluyendo los filtros de SoundCloud (pistas privadas/eliminadas y
previews de 30s). No depende de red ni de que exista yt-dlp en el entorno
-- son funciones puras, igual que _construir_comando en DownloadWorker.
"""
import json

from core.downloader import _build_search_command, _parse_search_line


def _linea(info: dict) -> str:
    return json.dumps(info)


# ── _build_search_command ───────────────────────────────────────────────────

def test_build_search_command_youtube():
    cmd = _build_search_command("yt-dlp.exe", "bad bunny", "YouTube", 10)
    assert cmd[0] == "yt-dlp.exe"
    assert cmd[1] == "ytsearch10:bad bunny"
    assert "--dump-json" in cmd
    assert "--no-playlist" in cmd


def test_build_search_command_soundcloud():
    cmd = _build_search_command("yt-dlp.exe", "lofi", "SoundCloud", 5)
    assert cmd[1] == "scsearch5:lofi"


def test_build_search_command_todo_usa_ytsearch():
    cmd = _build_search_command("yt-dlp.exe", "algo", "Todo", 12)
    assert cmd[1] == "ytsearch12:algo"


def test_build_search_command_fma_jamendo_anade_sufijo_creative_commons():
    # No existe extractor FMA/Jamendo en yt-dlp -- se busca en YouTube pero
    # añadiendo términos para sesgar los resultados hacia música libre.
    cmd = _build_search_command("yt-dlp.exe", "piano", "FMA / Jamendo", 8)
    assert cmd[1] == "ytsearch8:piano creative commons free music"


def test_build_search_command_fuente_desconocida_cae_a_ytsearch():
    cmd = _build_search_command("yt-dlp.exe", "x", "ExtractorFuturoQueNoExiste", 5)
    assert cmd[1] == "ytsearch5:x"


# ── _parse_search_line ──────────────────────────────────────────────────────

def test_parse_search_line_youtube_basico():
    linea = _linea({
        "title": "Cancion X", "uploader": "Artista Y", "duration": 185,
        "extractor_key": "Youtube", "webpage_url": "https://youtube.com/watch?v=abc",
        "id": "abc",
    })
    resultado = _parse_search_line(linea, "YouTube")
    assert resultado["title"] == "Cancion X"
    assert resultado["artist"] == "Artista Y"
    assert resultado["duration"] == "3:05"
    assert resultado["source"] == "YouTube"
    assert resultado["url"] == "https://youtube.com/watch?v=abc"
    assert resultado["id"] == "abc"


def test_parse_search_line_soundcloud_marca_fuente_por_extractor():
    linea = _linea({
        "title": "Beat", "uploader": "DJ Z", "duration": 200,
        "extractor_key": "Soundcloud", "webpage_url": "https://soundcloud.com/x/y",
    })
    resultado = _parse_search_line(linea, "SoundCloud")
    assert resultado["source"] == "SoundCloud"


def test_parse_search_line_fma_jamendo_mantiene_su_etiqueta_aunque_venga_de_youtube():
    linea = _linea({
        "title": "Free Song", "uploader": "CC Artist", "duration": 120,
        "extractor_key": "Youtube", "webpage_url": "https://youtube.com/watch?v=free",
    })
    resultado = _parse_search_line(linea, "FMA / Jamendo")
    assert resultado["source"] == "FMA / Jamendo"


def test_parse_search_line_sin_uploader_cae_a_artist_y_luego_desconocido():
    linea = _linea({
        "title": "X", "duration": 60, "extractor_key": "Youtube",
        "webpage_url": "https://youtube.com/watch?v=x", "artist": "Solista",
    })
    assert _parse_search_line(linea, "YouTube")["artist"] == "Solista"

    linea2 = _linea({
        "title": "X", "duration": 60, "extractor_key": "Youtube",
        "webpage_url": "https://youtube.com/watch?v=x2",
    })
    assert _parse_search_line(linea2, "YouTube")["artist"] == "Desconocido"


def test_parse_search_line_descarta_pista_soundcloud_privada_o_eliminada():
    linea = _linea({
        "title": "X", "uploader": "Y", "duration": 200,
        "extractor_key": "Soundcloud",
        "webpage_url": "https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A12345",
    })
    assert _parse_search_line(linea, "SoundCloud") is None


def test_parse_search_line_descarta_preview_soundcloud_de_30s_o_menos():
    linea = _linea({
        "title": "X", "uploader": "Y", "duration": 25,
        "extractor_key": "Soundcloud", "webpage_url": "https://soundcloud.com/x/y",
    })
    assert _parse_search_line(linea, "SoundCloud") is None


def test_parse_search_line_no_descarta_duracion_corta_fuera_de_soundcloud():
    # El filtro de "preview de 30s" es específico de SoundCloud -- un short
    # real de YouTube de 20s no debe descartarse por la misma regla.
    linea = _linea({
        "title": "Short", "uploader": "Y", "duration": 20,
        "extractor_key": "Youtube", "webpage_url": "https://youtube.com/watch?v=short",
    })
    assert _parse_search_line(linea, "YouTube") is not None


def test_parse_search_line_ignora_json_invalido():
    assert _parse_search_line("esto no es json", "YouTube") is None


def test_parse_search_line_descarta_sin_url():
    linea = _linea({"title": "X", "uploader": "Y", "duration": 10, "webpage_url": ""})
    assert _parse_search_line(linea, "YouTube") is None


def test_parse_search_line_formatea_duracion_mmss():
    linea = _linea({
        "title": "X", "uploader": "Y", "duration": 65,
        "extractor_key": "Youtube", "webpage_url": "https://youtube.com/watch?v=x",
    })
    assert _parse_search_line(linea, "YouTube")["duration"] == "1:05"

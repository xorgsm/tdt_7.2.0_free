"""
Cliente de Soulseek -- vía slskd, un proceso externo (nunca empaquetado
ni enlazado: es AGPLv3 + Additional Terms, ver
docs/superpowers/specs/2026-08-18-integracion-soulseek-design.md para el
motivo). Se descarga bajo demanda desde las releases oficiales de
GitHub, igual que core.downloader.ensure_yt_dlp() hace con yt-dlp.exe, y
se controla por HTTP contra su API REST local -- nunca se importa ni se
enlaza código de slskd en este proceso.

Coder By X@R
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from core.config import get_app_data_dir
from core.logger import get_logger

log = get_logger(__name__)

SLSKD_RELEASES_API_URL = "https://api.github.com/repos/slskd/slskd/releases/latest"
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_SLSKD_ZIP_BYTES = 250 * 1024 * 1024
MAX_SLSKD_EXTRACTED_BYTES = 750 * 1024 * 1024
API_TIMEOUT_SECONDS = 10
DEFAULT_HTTP_PORT = 5030
PUERTO_RANGO = range(DEFAULT_HTTP_PORT, DEFAULT_HTTP_PORT + 10)

# slskd abre además un puerto P2P real de Soulseek (--slsk-listen-port,
# valor por defecto 50300) que no tiene nada que ver con el HTTP de arriba.
# Si no se especifica, usa ese 50300 fijo -- y en Windows con Hyper-V/WSL
# suele caer dentro de un rango de puertos que el sistema excluye para uso
# de aplicaciones (netsh interface ipv4 show excludedportrange), lo que
# hace que todo el proceso de slskd muera al arrancar (ListenException,
# "Hosting failed to start") antes de exponer la API HTTP -- y entonces
# _esperar_api() nunca responde en NINGÚN puerto HTTP de PUERTO_RANGO,
# porque el problema real nunca fue el puerto HTTP. Se varía junto con el
# puerto HTTP en el mismo bucle de reintentos para no depender de que ese
# 50300 fijo esté libre.
DEFAULT_SLSK_LISTEN_PORT = 53270
SLSK_PUERTO_RANGO = range(DEFAULT_SLSK_LISTEN_PORT, DEFAULT_SLSK_LISTEN_PORT + 10)

_CIERRE_TIMEOUT_SEGUNDOS = 5
_BUSQUEDA_INTENTOS = 30
_BUSQUEDA_ESPERA = 1.5

# Evita que se abra una consola negra al lanzar slskd.exe desde la GUI
# (mismo criterio que core/downloader.py con yt-dlp.exe/ffmpeg).
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _slskd_dir() -> Path:
    d = get_app_data_dir() / "tools" / "slskd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slskd_exe_path() -> Optional[Path]:
    """Busca slskd.exe ya extraído, en cualquier profundidad -- el zip
    oficial lo trae en la raíz, pero no se asume la estructura exacta
    por si un release futuro la cambia."""
    encontrados = list(_slskd_dir().rglob("slskd.exe"))
    return encontrados[0] if encontrados else None


def _extraer_zip_seguro(zf: zipfile.ZipFile, destino: Path) -> None:
    """
    Como ZipFile.extractall(), pero rechaza cualquier entrada que intente
    escapar de `destino` (rutas absolutas o con '..'). El zip viene de las
    releases oficiales de GitHub, pero sigue siendo contenido descargado de
    la red -- un asset comprometido o un mirror suplantado con entradas
    tipo "../../../AppData/Roaming/..." podría escribir fuera de
    tools/slskd si no se valida cada ruta antes de extraerla (zip-slip).
    """
    raiz = destino.resolve()
    if sum(member.file_size for member in zf.infolist()) > MAX_SLSKD_EXTRACTED_BYTES:
        raise RuntimeError("El zip de slskd supera el tamaño descomprimido permitido")
    for member in zf.infolist():
        objetivo = (raiz / member.filename).resolve()
        if objetivo != raiz and raiz not in objetivo.parents:
            raise RuntimeError(
                f"El zip de slskd contiene una ruta fuera de destino: {member.filename!r}"
            )
    zf.extractall(destino)


def ensure_slskd(progress_cb=None) -> str:
    """
    Devuelve la ruta a slskd.exe, descargándolo la primera vez si hace
    falta. A diferencia de yt-dlp.exe (nombre de asset estable en la URL
    de "latest"), los assets de slskd incluyen la versión en el nombre
    (slskd-0.26.0-win-x64.zip), así que primero hay que resolver la
    versión más reciente vía la API de GitHub.
    """
    existente = _slskd_exe_path()
    if existente is not None:
        hash_path = existente.with_suffix(".exe.sha256")
        try:
            expected_local = hash_path.read_text(encoding="ascii").strip().lower()
            actual_local = hashlib.sha256(existente.read_bytes()).hexdigest()
            if hmac.compare_digest(actual_local, expected_local):
                return str(existente)
        except OSError:
            pass
        existente.unlink(missing_ok=True)
        hash_path.unlink(missing_ok=True)

    peticion = urllib.request.Request(
        SLSKD_RELEASES_API_URL, headers={"User-Agent": "TDT-Radio-VIP"}
    )
    with urllib.request.urlopen(peticion, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
        release = json.loads(resp.read().decode("utf-8"))

    asset = next(
        (a for a in release.get("assets", []) if a.get("name", "").endswith("-win-x64.zip")),
        None,
    )
    if asset is None:
        raise RuntimeError("La última versión de slskd no publica un asset win-x64.zip")
    digest_field = asset.get("digest", "")
    if not digest_field.startswith("sha256:") or len(digest_field) != 71:
        raise RuntimeError("GitHub no publicó el SHA-256 verificable del asset de slskd")
    expected_digest = digest_field.removeprefix("sha256:").lower()

    zip_path = _slskd_dir() / "slskd.zip"
    parcial = zip_path.with_suffix(".zip.part")
    peticion_zip = urllib.request.Request(
        asset["browser_download_url"], headers={"User-Agent": "TDT-Radio-VIP"}
    )
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(peticion_zip, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_SLSKD_ZIP_BYTES:
                raise RuntimeError("El zip de slskd supera el tamaño máximo permitido")
            bajado = 0
            with open(parcial, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    if bajado + len(chunk) > MAX_SLSKD_ZIP_BYTES:
                        raise RuntimeError("El zip de slskd supera el tamaño máximo permitido")
                    fh.write(chunk)
                    digest.update(chunk)
                    bajado += len(chunk)
                    if progress_cb and total:
                        progress_cb(bajado / total)
        if not hmac.compare_digest(digest.hexdigest(), expected_digest):
            raise RuntimeError("El SHA-256 del zip de slskd no coincide con GitHub")
        os.replace(parcial, zip_path)
    except Exception:
        log.exception("Fallo descargando %s", asset["browser_download_url"])
        try:
            if parcial.exists():
                parcial.unlink()
        except OSError:
            pass
        raise

    with zipfile.ZipFile(zip_path) as zf:
        _extraer_zip_seguro(zf, _slskd_dir())
    zip_path.unlink(missing_ok=True)

    exe = _slskd_exe_path()
    if exe is None:
        raise RuntimeError("El zip descargado de slskd no contenía slskd.exe")
    exe.with_suffix(".exe.sha256").write_text(
        hashlib.sha256(exe.read_bytes()).hexdigest(), encoding="ascii"
    )
    return str(exe)


class SoulseekClient:
    def __init__(self):
        self._proceso = None
        self.puerto: Optional[int] = None
        # Puesto a True por cerrar() -- conectar() (que corre en un
        # QThread aparte, _EnsureWorker) lo consulta entre cada intento de
        # puerto y en cada sondeo de _esperar_api() para poder abortar en
        # marcha. Sin esto, si la app se cierra mientras conectar() sigue
        # buscando puerto libre (hasta ~10s por puerto), cerrar() no
        # encuentra nada en self._proceso todavía (sigue siendo None) y no
        # hace nada -- y el slskd.exe que conectar() arranca *después* de
        # que cerrar() ya ha pasado queda huérfano, porque nadie vuelve a
        # llamar a cerrar() sobre él.
        self._cerrando = False

    @property
    def conectado(self) -> bool:
        return self._proceso is not None and self._proceso.poll() is None

    # ---------- ciclo de vida ----------

    def conectar(self, username: str, password: str, downloads_dir: str) -> Optional[str]:
        if self.conectado:
            return None
        exe = _slskd_exe_path()
        if exe is None:
            return "slskd todavía no se ha descargado."

        entorno = os.environ.copy()
        entorno["SLSKD_SLSK_USERNAME"] = username
        entorno["SLSKD_SLSK_PASSWORD"] = password

        for puerto, puerto_slsk in zip(PUERTO_RANGO, SLSK_PUERTO_RANGO):
            if self._cerrando:
                break
            comando = [
                str(exe), "--headless", "--no-auth",
                "--http-port", str(puerto),
                "--http-ip-address", "127.0.0.1",
                "--slsk-listen-port", str(puerto_slsk),
                "--app-dir", str(_slskd_dir() / "appdata"),
                "--downloads", downloads_dir,
            ]
            try:
                proceso = subprocess.Popen(
                    comando, env=entorno, creationflags=_CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                return f"No se pudo arrancar slskd: {exc}"

            self.puerto = puerto
            api_ok = self._esperar_api()
            if self._cerrando:
                # cerrar() se disparó mientras esperábamos: no dejar este
                # proceso vivo aunque la API haya llegado a responder.
                proceso.kill()
                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.puerto = None
                break
            if api_ok:
                self._proceso = proceso
                return None

            proceso.kill()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self.puerto = None

        if self._cerrando:
            return "Cierre en curso; conexión cancelada."
        return "No se pudo arrancar slskd: no se encontró un puerto libre."

    def _esperar_api(self, intentos: int = 20, espera: float = 0.5) -> bool:
        for _ in range(intentos):
            if self._cerrando:
                return False
            try:
                self._get("/api/v0/application")
                return True
            except (OSError, ValueError):
                time.sleep(espera)
        return False

    def esta_logueado(self) -> bool:
        if not self.conectado:
            return False
        try:
            estado = self._get("/api/v0/application")
        except (OSError, ValueError):
            return False
        return bool(estado.get("server", {}).get("isLoggedIn"))

    def cerrar(self, on_wait=None):
        # Primero que nada: le dice a conectar() (si sigue corriendo en su
        # QThread) que aborte en el próximo punto de comprobación, para que
        # no deje un slskd.exe nuevo arrancando justo después de este cierre.
        self._cerrando = True
        proceso = self._proceso
        if proceso is None:
            return
        self._proceso = None
        self.puerto = None

        proceso.terminate()
        deadline = time.monotonic() + _CIERRE_TIMEOUT_SEGUNDOS
        if not self._esperar_fin(proceso, deadline, on_wait):
            proceso.kill()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def _esperar_fin(self, proceso, deadline, on_wait=None, intervalo=0.05) -> bool:
        while proceso.poll() is None and time.monotonic() < deadline:
            if on_wait:
                on_wait()
            time.sleep(intervalo)
        return proceso.poll() is not None

    # ---------- HTTP ----------

    def _request(self, method: str, path: str, body=None):
        url = f"http://127.0.0.1:{self.puerto}{path}"
        datos = json.dumps(body).encode("utf-8") if body is not None else None
        peticion = urllib.request.Request(url, data=datos, method=method)
        if datos is not None:
            peticion.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(peticion, timeout=API_TIMEOUT_SECONDS) as resp:
            crudo = resp.read()
        return json.loads(crudo) if crudo else None

    def _get(self, path: str):
        return self._request("GET", path)

    def _post(self, path: str, body):
        return self._request("POST", path, body)

    def _delete(self, path: str):
        return self._request("DELETE", path)

    # ---------- búsqueda y descarga ----------

    def buscar(self, texto: str) -> list:
        creada = self._post("/api/v0/searches", {"searchText": texto})
        id_busqueda = creada["id"]

        resultado = creada
        for _ in range(_BUSQUEDA_INTENTOS):
            resultado = self._get(f"/api/v0/searches/{id_busqueda}?includeResponses=true")
            # slskd marca isComplete cuando expira SU propia ventana de
            # espera, no cuando la red ha dejado de responder de verdad --
            # para términos poco comunes los peers pueden tardar más en
            # contestar. Si ya hay resultados, se corta ahí (caso normal,
            # rápido); si isComplete llega sin nada todavía, se sigue
            # insistiendo hasta agotar los intentos en vez de rendirse.
            if resultado.get("isComplete") and resultado.get("responses"):
                break
            time.sleep(_BUSQUEDA_ESPERA)

        archivos = []
        for respuesta in resultado.get("responses", []):
            username = respuesta.get("username", "")
            velocidad = respuesta.get("uploadSpeed", 0)
            cola = respuesta.get("queueLength", 0)
            for f in respuesta.get("files", []):
                archivos.append({
                    "username": username,
                    "filename": f.get("filename", ""),
                    "size": f.get("size", 0),
                    "bitrate": f.get("bitRate"),
                    "extension": f.get("extension", ""),
                    "upload_speed": velocidad,
                    "queue_length": cola,
                })
        return archivos

    def descargar(self, username: str, filename: str, size: int) -> Optional[str]:
        codificado = urllib.parse.quote(username, safe="")
        try:
            self._post(f"/api/v0/transfers/downloads/{codificado}", [
                {"filename": filename, "size": size}
            ])
        except Exception as exc:
            return f"No se pudo encolar la descarga: {exc}"
        return None

    def listar_descargas(self) -> list:
        grupos = self._get("/api/v0/transfers/downloads") or []
        descargas = []
        for grupo in grupos:
            username = grupo.get("username", "")
            for directorio in grupo.get("directories", []):
                for f in directorio.get("files", []):
                    descargas.append({
                        "id": f.get("id"),
                        "username": username,
                        "filename": f.get("filename", ""),
                        "size": f.get("size", 0),
                        "state": f.get("state", ""),
                        "percent_complete": f.get("percentComplete", 0.0),
                        "bytes_transferred": f.get("bytesTransferred", 0),
                        "average_speed": f.get("averageSpeed", 0.0),
                    })
        return descargas

    def cancelar_descarga(self, username: str, id_: str) -> None:
        """Cancela Y elimina esa transferencia concreta en una sola llamada
        (?remove=true) -- sin ese parámetro, slskd solo la marca como
        'Cancelled' y la sigue devolviendo en listar_descargas() hasta que
        se llama aparte a limpiar_completadas(), que además borra TODAS las
        transferencias terminadas (completadas/con error incluidas), no
        solo la que se acaba de cancelar."""
        codificado = urllib.parse.quote(username, safe="")
        self._delete(f"/api/v0/transfers/downloads/{codificado}/{id_}?remove=true")

    def limpiar_completadas(self) -> None:
        """Borra del lado de slskd las descargas ya terminadas (completadas,
        canceladas, con error). slskd no las olvida solo -- listar_descargas()
        las sigue devolviendo indefinidamente si no se llama a esto, lo que
        hace más lento cada refresco de la lista cuanto más se acumulan."""
        self._delete("/api/v0/transfers/downloads/all/completed")

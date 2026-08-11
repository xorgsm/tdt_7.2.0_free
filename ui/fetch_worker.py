"""
Hilo de trabajo genérico para no bloquear la interfaz mientras se hace una
llamada de red o de E/S: TV, radio, EPG e importación de listas M3U lo
usan todos por igual.

Extraído de ui/main_window.py (donde antes vivía como clase interna) para
que ui/epg_controller.py y ui/library_controller.py puedan usarlo también
sin tener que importar ui/main_window.py -- eso habría creado un import
circular, ya que main_window.py es quien construye esos controladores.

Coder By X@R
"""
import threading
from typing import Iterable

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, Qt, Signal, Slot


class ActiveWorkerRegistry:
    """Mantiene referencias fuertes a los FetchWorker activos de la app."""

    def __init__(self):
        self._lock = threading.Lock()
        self._workers = set()
        self._closing = False

    def register(self, worker) -> bool:
        with self._lock:
            if self._closing:
                return False
            self._workers.add(worker)
            return True

    def start_worker(self, worker, start_thread) -> bool:
        """Registra y arranca un worker como una sola transición de cierre."""
        with self._lock:
            if self._closing:
                return False
            self._workers.add(worker)
            try:
                start_thread()
            except Exception:
                self._workers.discard(worker)
                raise
            return True

    def remove(self, worker) -> None:
        with self._lock:
            self._workers.discard(worker)

    def workers(self) -> tuple:
        with self._lock:
            return tuple(self._workers)

    def begin_shutdown(self) -> bool:
        with self._lock:
            if self._closing:
                return False
            self._closing = True
            return True


def process_events_during_shutdown() -> None:
    """Procesa callbacks de limpieza sin aceptar acciones nuevas del usuario."""
    application = QCoreApplication.instance()
    if application is not None:
        application.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        )


def shutdown_workers(workers: Iterable[QThread], wait_slice_ms: int = 50) -> None:
    """Solicita el cierre cooperativo de todos los hilos y espera su final."""
    active_workers = [worker for worker in workers if worker is not None]
    for worker in active_workers:
        if isinstance(worker, FetchWorker):
            worker.cancel()
        else:
            worker.requestInterruption()

    while any(worker.isRunning() for worker in active_workers):
        for worker in active_workers:
            if worker.isRunning():
                worker.wait(wait_slice_ms)
        process_events_during_shutdown()
    # Entrega los ``finished`` encolados que liberan las referencias del
    # registro una vez que ``isRunning()`` ya es falso.
    process_events_during_shutdown()


class FetchWorker(QThread):
    """Ejecuta una función de red en segundo plano para no bloquear la UI."""
    done = Signal(object)
    _active_registry = ActiveWorkerRegistry()

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._state_lock = threading.Lock()
        self._cancelled = False
        self._done_committed = False
        self.finished.connect(
            self._remove_from_active_registry,
            Qt.ConnectionType.QueuedConnection,
        )

    @classmethod
    def active_workers(cls) -> tuple:
        return cls._active_registry.workers()

    @classmethod
    def begin_shutdown(cls) -> bool:
        return cls._active_registry.begin_shutdown()

    def start(self, *args, **kwargs):
        qthread_start = super().start
        self._active_registry.start_worker(
            self,
            lambda: qthread_start(*args, **kwargs),
        )

    def cancel(self) -> None:
        with self._state_lock:
            if self._done_committed:
                return
            self._cancelled = True
            self.requestInterruption()

    def _emit_done(self, result) -> None:
        self.done.emit(result)

    @Slot()
    def _remove_from_active_registry(self) -> None:
        """Libera la referencia solo al observar ``finished`` en el hilo UI."""
        self._active_registry.remove(self)

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
        except Exception:
            result = None
        with self._state_lock:
            if self._cancelled:
                return
            self._done_committed = True
        self._emit_done(result)

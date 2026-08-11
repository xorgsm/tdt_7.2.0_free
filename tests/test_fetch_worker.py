import queue
import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtTest import QSignalSpy

from ui.fetch_worker import ActiveWorkerRegistry, FetchWorker, shutdown_workers


_application_instance = None
THREAD_TIMEOUT_SECONDS = 60
THREAD_TIMEOUT_MS = THREAD_TIMEOUT_SECONDS * 1_000


def _application():
    global _application_instance
    _application_instance = QCoreApplication.instance() or QCoreApplication([])
    return _application_instance


def test_cancelled_worker_does_not_emit_done_after_function_returns():
    _application()
    function_started = threading.Event()
    release_function = threading.Event()

    def blocking_function():
        function_started.set()
        release_function.wait()
        return "finished"

    worker = FetchWorker(blocking_function)
    done_spy = QSignalSpy(worker.done)
    try:
        worker.start()
        assert function_started.wait(THREAD_TIMEOUT_SECONDS)

        worker.cancel()
        release_function.set()

        assert worker.wait(THREAD_TIMEOUT_MS)
        _application().processEvents()
        assert done_spy.count() == 0
    finally:
        release_function.set()
        assert worker.wait(THREAD_TIMEOUT_MS)


def test_shutdown_workers_interrupts_all_workers_and_waits_for_them_to_finish():
    _application()
    first_started = threading.Event()
    second_started = threading.Event()
    release_workers = threading.Event()
    first_interrupted = threading.Event()
    second_interrupted = threading.Event()
    finished_at = []

    def blocking_function(started, interruption_seen):
        started.set()
        release_workers.wait()
        if QThread.currentThread().isInterruptionRequested():
            interruption_seen.set()
        finished_at.append(time.monotonic())

    first_worker = FetchWorker(blocking_function, first_started, first_interrupted)
    second_worker = FetchWorker(blocking_function, second_started, second_interrupted)
    try:
        first_worker.start()
        second_worker.start()
        assert first_started.wait(THREAD_TIMEOUT_SECONDS)
        assert second_started.wait(THREAD_TIMEOUT_SECONDS)

        QTimer.singleShot(30, release_workers.set)
        shutdown_workers([first_worker, None, second_worker], wait_slice_ms=5)
        returned_at = time.monotonic()

        assert first_interrupted.is_set()
        assert second_interrupted.is_set()
        assert not first_worker.isRunning()
        assert not second_worker.isRunning()
        assert len(finished_at) == 2
        assert all(finished <= returned_at for finished in finished_at)
    finally:
        release_workers.set()
        assert first_worker.wait(THREAD_TIMEOUT_MS)
        assert second_worker.wait(THREAD_TIMEOUT_MS)


def test_shutdown_event_pump_excludes_user_input(monkeypatch):
    from ui import fetch_worker

    process_events_calls = []
    application = SimpleNamespace(
        processEvents=lambda *args: process_events_calls.append(args)
    )
    monkeypatch.setattr(
        fetch_worker,
        "QCoreApplication",
        SimpleNamespace(instance=lambda: application),
    )

    fetch_worker.process_events_during_shutdown()

    assert process_events_calls == [
        (QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents,)
    ]


def test_close_event_stops_reminder_timer_before_first_filtered_event_pump(
    monkeypatch,
):
    from ui import main_window

    calls = []
    received_callbacks = []

    def filtered_event_pump():
        calls.append("filtered_event_pump")

    def stop_recorder(*, on_wait):
        received_callbacks.append(on_wait)
        calls.append("recorder.stop")
        on_wait()
        return None, False

    def shutdown_downloads(*, on_wait):
        received_callbacks.append(on_wait)
        calls.append("downloads.shutdown")
        on_wait()

    monkeypatch.setattr(
        main_window,
        "process_events_during_shutdown",
        filtered_event_pump,
        raising=False,
    )
    monkeypatch.setattr(
        main_window,
        "QApplication",
        SimpleNamespace(processEvents=lambda: calls.append("unfiltered_event_pump")),
    )
    monkeypatch.setattr(
        main_window.FetchWorker,
        "begin_shutdown",
        lambda: calls.append("begin_shutdown"),
    )
    monkeypatch.setattr(main_window.FetchWorker, "active_workers", lambda: ())
    monkeypatch.setattr(
        main_window,
        "shutdown_workers",
        lambda workers: calls.append(("shutdown_workers", workers)),
    )

    window = SimpleNamespace(
        _is_closing=False,
        _reminder_timer=SimpleNamespace(stop=lambda: calls.append("timer.stop")),
        _tray_icon=SimpleNamespace(hide=lambda: calls.append("tray.hide")),
        _media_keys=SimpleNamespace(stop=lambda: calls.append("media_keys.stop")),
        recorder=SimpleNamespace(is_recording=True, stop=stop_recorder),
        _scheduled_recording_active=None,
        player=SimpleNamespace(
            stop=lambda: calls.append("player.stop"),
            release=lambda: calls.append("player.release"),
        ),
        equalizer=SimpleNamespace(stop=lambda: calls.append("equalizer.stop")),
        _cast_session=SimpleNamespace(
            disconnect=lambda: calls.append("cast.disconnect")
        ),
        _dlna_session=SimpleNamespace(
            disconnect=lambda: calls.append("dlna.disconnect")
        ),
        download_panel=SimpleNamespace(shutdown=shutdown_downloads),
        _taskbar=SimpleNamespace(cleanup=lambda: calls.append("taskbar.cleanup")),
    )
    event = SimpleNamespace(
        accept=lambda: calls.append("event.accept"),
        ignore=lambda: calls.append("event.ignore"),
    )

    main_window.MainWindow.closeEvent(window, event)

    assert calls.index("timer.stop") < calls.index("filtered_event_pump")
    assert received_callbacks == [filtered_event_pump, filtered_event_pump]
    assert "unfiltered_event_pump" not in calls


def test_tray_timer_callbacks_do_nothing_while_window_is_closing(monkeypatch):
    from ui import tray_controller

    calls = []
    monkeypatch.setattr(
        tray_controller.epg_reminders,
        "check_due",
        lambda parser: calls.append(("check_due", parser)) or [],
    )
    monkeypatch.setattr(
        tray_controller.recurring_recordings,
        "sync_into_schedule",
        lambda: calls.append("sync_into_schedule"),
    )
    monkeypatch.setattr(
        tray_controller.recording_schedule,
        "check_stops_due",
        lambda parser: calls.append(("check_stops_due", parser)) or [],
    )
    monkeypatch.setattr(
        tray_controller.recording_schedule,
        "check_starts_due",
        lambda parser: calls.append(("check_starts_due", parser)) or [],
    )
    controller = tray_controller.TrayReminderController(
        SimpleNamespace(_is_closing=True)
    )

    controller.check_epg_reminders()
    controller.check_scheduled_recordings()

    assert calls == []


def test_scheduled_stop_reentrant_close_cleans_up_without_starting_next_recording(
    monkeypatch,
):
    """Una parada que bombea eventos no puede arrancar otra grabación al cerrar."""
    from ui import tray_controller

    calls = []
    stopped = SimpleNamespace(
        tvg_id="la-1",
        title="Programa terminado",
        start="20260809200000",
        stop="20260809210000",
    )
    next_recording = SimpleNamespace(
        tvg_id="la-2",
        title="Programa siguiente",
        start="20260809210000",
        stop="20260809220000",
        channel_url="http://stream.example/2",
        channel_name="La 2",
    )

    class ReentrantRecorder:
        is_recording = True

        def stop(self, *, on_wait):
            calls.append("recorder.stop")
            # Simula el closeEvent entregado por QApplication.processEvents().
            window._is_closing = True
            self.is_recording = False
            return None, False

        def start(self, *_args):
            calls.append("recorder.start")
            return "grabacion.mp4"

    def forbidden_ui_mutation(*_args):
        calls.append("ui.after_close")

    window = SimpleNamespace(
        _is_closing=False,
        _scheduled_recording_active=stopped,
        recorder=ReentrantRecorder(),
        record_btn=SimpleNamespace(
            setChecked=forbidden_ui_mutation,
            setGraphicsEffect=forbidden_ui_mutation,
        ),
        _tray_icon=SimpleNamespace(showMessage=forbidden_ui_mutation),
        statusBar=lambda: SimpleNamespace(showMessage=forbidden_ui_mutation),
        _make_glow=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(tray_controller.recurring_recordings, "sync_into_schedule", lambda: None)
    monkeypatch.setattr(
        tray_controller.recording_schedule,
        "check_stops_due",
        lambda _parser: [stopped],
    )
    monkeypatch.setattr(
        tray_controller.recording_schedule,
        "check_starts_due",
        lambda _parser: calls.append("check_starts_due") or [next_recording],
    )
    monkeypatch.setattr(
        tray_controller.recording_schedule,
        "mark_done",
        lambda tvg_id, title, start: calls.append(("mark_done", tvg_id, title, start)),
    )
    monkeypatch.setattr(
        tray_controller.rec_module.Recorder,
        "ffmpeg_available",
        lambda: True,
    )

    tray_controller.TrayReminderController(window).check_scheduled_recordings()

    assert ("mark_done", "la-1", "Programa terminado", "20260809200000") in calls
    assert window._scheduled_recording_active is None
    assert "check_starts_due" not in calls
    assert "recorder.start" not in calls
    assert "ui.after_close" not in calls


def test_cancel_after_done_commit_does_not_suppress_the_already_committed_signal():
    _application()
    emission_committed = threading.Event()
    allow_emission = threading.Event()

    class PausedEmissionWorker(FetchWorker):
        def _emit_done(self, result):
            emission_committed.set()
            allow_emission.wait()
            super()._emit_done(result)

    worker = PausedEmissionWorker(lambda: "finished")
    done_spy = QSignalSpy(worker.done)
    try:
        worker.start()
        assert emission_committed.wait(THREAD_TIMEOUT_SECONDS)

        worker.cancel()
        assert not worker.isInterruptionRequested()
        allow_emission.set()

        assert worker.wait(THREAD_TIMEOUT_MS)
        _application().processEvents()
        assert done_spy.count() == 1
    finally:
        allow_emission.set()
        assert worker.wait(THREAD_TIMEOUT_MS)


def test_active_registry_keeps_replaced_workers_until_each_one_finishes():
    _application()
    first_started = threading.Event()
    second_started = threading.Event()
    release_workers = threading.Event()

    def blocking_function(started):
        started.set()
        release_workers.wait()

    first_worker = FetchWorker(blocking_function, first_started)
    latest_worker = first_worker
    second_worker = FetchWorker(blocking_function, second_started)
    latest_worker = second_worker
    try:
        first_worker.start()
        second_worker.start()
        assert first_started.wait(THREAD_TIMEOUT_SECONDS)
        assert second_started.wait(THREAD_TIMEOUT_SECONDS)

        assert latest_worker is second_worker
        assert {first_worker, second_worker}.issubset(FetchWorker.active_workers())

        QTimer.singleShot(30, release_workers.set)
        shutdown_workers(FetchWorker.active_workers(), wait_slice_ms=5)

        assert not first_worker.isRunning()
        assert not second_worker.isRunning()
        assert first_worker not in FetchWorker.active_workers()
        assert second_worker not in FetchWorker.active_workers()
    finally:
        release_workers.set()
        assert first_worker.wait(THREAD_TIMEOUT_MS)
        assert second_worker.wait(THREAD_TIMEOUT_MS)


def test_active_registry_keeps_worker_after_fetch_run_returns_until_finished_is_observed():
    _application()
    fetch_run_returned = threading.Event()
    allow_thread_exit = threading.Event()
    registry = ActiveWorkerRegistry()

    class PausedThreadExitWorker(FetchWorker):
        _active_registry = registry

        def run(self):
            super().run()
            fetch_run_returned.set()
            allow_thread_exit.wait()

    worker = PausedThreadExitWorker(lambda: "finished")
    try:
        worker.start()
        assert fetch_run_returned.wait(THREAD_TIMEOUT_SECONDS)

        assert worker.isRunning()
        assert worker in PausedThreadExitWorker.active_workers()

        allow_thread_exit.set()
        assert worker.wait(THREAD_TIMEOUT_MS)
        assert not worker.isRunning()
        assert worker in PausedThreadExitWorker.active_workers()

        _application().processEvents()
        assert worker not in PausedThreadExitWorker.active_workers()
    finally:
        allow_thread_exit.set()
        worker.cancel()
        assert worker.wait(THREAD_TIMEOUT_MS)
        _application().processEvents()


def test_active_registry_rejects_new_workers_after_closing_begins():
    registry = ActiveWorkerRegistry()
    first_worker = object()
    second_worker = object()

    assert registry.register(first_worker)
    assert registry.begin_shutdown()
    assert not registry.begin_shutdown()
    assert not registry.register(second_worker)
    assert registry.workers() == (first_worker,)


def test_fetch_worker_does_not_start_after_shutdown_begins():
    registry = ActiveWorkerRegistry()
    function_called = threading.Event()

    class ClosingRegistryWorker(FetchWorker):
        _active_registry = registry

    worker = ClosingRegistryWorker(function_called.set)
    try:
        assert ClosingRegistryWorker.begin_shutdown()

        worker.start()

        assert worker.wait(THREAD_TIMEOUT_MS)
        assert not worker.isRunning()
        assert not function_called.is_set()
        assert ClosingRegistryWorker.active_workers() == ()
    finally:
        worker.cancel()
        assert worker.wait(THREAD_TIMEOUT_MS)


def test_begin_shutdown_cannot_overtake_the_qthread_start_transition():
    transition_events = queue.Queue()
    allow_qthread_start = threading.Event()
    function_started = threading.Event()
    release_function = threading.Event()
    shutdown_lock_attempted = threading.Event()
    shutdown_began = threading.Event()
    shutdown_snapshot_taken = threading.Event()
    shutdown_complete = threading.Event()
    start_complete = threading.Event()
    thread_errors = []
    shutdown_snapshot = []
    shutdown_caller = None

    class ObservedLock:
        def __init__(self):
            self._lock = threading.Lock()

        def __enter__(self):
            if threading.current_thread() is shutdown_caller:
                shutdown_lock_attempted.set()
            self._lock.acquire()
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback):
            self._lock.release()

    class InterleavingRegistry(ActiveWorkerRegistry):
        def start_worker(self, worker, start_thread):
            def paused_start():
                transition_events.put("before_qthread_start")
                assert allow_qthread_start.wait(THREAD_TIMEOUT_SECONDS)
                start_thread()

            return super().start_worker(worker, paused_start)

    registry = InterleavingRegistry()
    registry._lock = ObservedLock()

    class InterleavingWorker(FetchWorker):
        _active_registry = registry

    def blocking_function():
        function_started.set()
        transition_events.put("function_started")
        release_function.wait()

    worker = InterleavingWorker(blocking_function)

    def start_worker():
        try:
            worker.start()
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            transition_events.put("start_returned")
            start_complete.set()

    def close_registry():
        try:
            assert registry.begin_shutdown()
            shutdown_began.set()
            shutdown_snapshot.extend(registry.workers())
            shutdown_snapshot_taken.set()
            shutdown_workers(shutdown_snapshot, wait_slice_ms=5)
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            shutdown_complete.set()

    start_caller = threading.Thread(target=start_worker)
    shutdown_caller = threading.Thread(target=close_registry)
    try:
        start_caller.start()
        assert transition_events.get(timeout=THREAD_TIMEOUT_SECONDS) == "before_qthread_start"

        shutdown_caller.start()
        assert shutdown_lock_attempted.wait(THREAD_TIMEOUT_SECONDS)
        assert not shutdown_began.is_set()

        allow_qthread_start.set()
        assert function_started.wait(THREAD_TIMEOUT_SECONDS)
        assert shutdown_began.wait(THREAD_TIMEOUT_SECONDS)
        assert shutdown_snapshot_taken.wait(THREAD_TIMEOUT_SECONDS)
        assert worker in shutdown_snapshot

        release_function.set()
        assert start_complete.wait(THREAD_TIMEOUT_SECONDS)
        assert shutdown_complete.wait(THREAD_TIMEOUT_SECONDS)
        start_caller.join(THREAD_TIMEOUT_SECONDS)
        shutdown_caller.join(THREAD_TIMEOUT_SECONDS)

        assert not start_caller.is_alive()
        assert not shutdown_caller.is_alive()
        assert not thread_errors
        assert not worker.isRunning()
    finally:
        allow_qthread_start.set()
        release_function.set()
        worker.cancel()
        assert worker.wait(THREAD_TIMEOUT_MS)
        if start_caller.is_alive():
            start_caller.join(THREAD_TIMEOUT_SECONDS)
        if shutdown_caller.is_alive():
            shutdown_caller.join(THREAD_TIMEOUT_SECONDS)


def test_tv_result_does_not_mutate_main_window_while_closing(monkeypatch):
    from ui import main_window

    calls = []
    monkeypatch.setattr(
        main_window.tv_channels,
        "filter_hidden",
        lambda channels: calls.append(("filter_hidden", channels)) or channels,
    )
    monkeypatch.setattr(
        main_window.tv_channels,
        "load_custom_channels",
        lambda: calls.append(("load_custom_channels",)) or [],
    )
    monkeypatch.setattr(
        main_window.tv_channels,
        "dedupe_channels",
        lambda channels: calls.append(("dedupe_channels", channels)) or channels,
    )
    window = SimpleNamespace(
        _is_closing=True,
        tv_channels_data=["unchanged"],
        lists=SimpleNamespace(
            refresh_group_filter=lambda: calls.append(("refresh_group_filter",)),
            populate_tv_list=lambda channels: calls.append(("populate_tv_list", channels)),
        ),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda *args: calls.append(("showMessage", args))
        ),
    )

    main_window.MainWindow._on_tv_channels_loaded(window, ["queued"])

    assert calls == []
    assert window.tv_channels_data == ["unchanged"]


def test_radio_result_does_not_mutate_main_window_while_closing(monkeypatch):
    from ui import main_window

    calls = []
    monkeypatch.setattr(
        main_window.radio_stations,
        "filter_hidden",
        lambda stations: calls.append(("filter_hidden", stations)) or stations,
    )
    monkeypatch.setattr(
        main_window.radio_stations,
        "load_custom_stations",
        lambda: calls.append(("load_custom_stations",)) or [],
    )
    window = SimpleNamespace(
        _is_closing=True,
        radio_stations_data=["unchanged"],
        lists=SimpleNamespace(
            populate_radio_list=lambda stations: calls.append(("populate_radio_list", stations))
        ),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda *args: calls.append(("showMessage", args))
        ),
    )

    main_window.MainWindow._on_radio_stations_loaded(window, ["queued"])

    assert calls == []
    assert window.radio_stations_data == ["unchanged"]


def test_update_result_does_not_open_dialog_while_main_window_is_closing(monkeypatch):
    from ui import main_window

    calls = []
    monkeypatch.setattr(
        main_window,
        "QMessageBox",
        SimpleNamespace(
            Yes=1,
            information=lambda *args: calls.append(("information", args)),
            question=lambda *args: calls.append(("question", args)) or 1,
        ),
    )
    monkeypatch.setattr(
        main_window,
        "QDesktopServices",
        SimpleNamespace(openUrl=lambda url: calls.append(("openUrl", url))),
    )
    window = SimpleNamespace(_is_closing=True)

    main_window.MainWindow._on_update_check_done(
        window,
        {"version": "999.0", "url": "https://example.invalid/update"},
    )

    assert calls == []


def test_epg_result_does_not_mutate_owner_while_closing():
    from ui.epg_controller import EpgController

    calls = []
    original_guide = {"existing": "guide"}
    window = SimpleNamespace(
        _is_closing=True,
        epg_guide=original_guide,
        playback=SimpleNamespace(
            update_epg_display=lambda: calls.append(("update_epg_display",))
        ),
        tv_channels_data=["existing channel"],
        lists=SimpleNamespace(
            populate_tv_list=lambda channels: calls.append(
                ("populate_tv_list", channels)
            )
        ),
    )
    controller = SimpleNamespace(win=window)

    EpgController._on_loaded(controller, {"queued": "guide"})

    assert window.epg_guide is original_guide
    assert calls == []


def test_epg_result_updates_owner_when_not_closing():
    from ui.epg_controller import EpgController

    calls = []
    guide = {"channel": "programme"}
    channels = ["loaded channel"]
    window = SimpleNamespace(
        _is_closing=False,
        epg_guide={},
        playback=SimpleNamespace(
            update_epg_display=lambda: calls.append(("update_epg_display",))
        ),
        tv_channels_data=channels,
        lists=SimpleNamespace(
            populate_tv_list=lambda received: calls.append(
                ("populate_tv_list", received)
            )
        ),
    )
    controller = SimpleNamespace(win=window)

    EpgController._on_loaded(controller, guide)

    assert window.epg_guide is guide
    assert calls == [
        ("update_epg_display",),
        ("populate_tv_list", channels),
    ]


def test_playlist_result_does_not_mutate_owner_or_open_dialog_while_closing(
    monkeypatch,
):
    from ui import library_controller

    calls = []
    original_channels = [SimpleNamespace(name="Existing")]
    queued_channel = SimpleNamespace(
        name="Queued",
        url="https://example.invalid/stream",
        logo="",
        group="Imported",
        tvg_id="queued-id",
    )
    monkeypatch.setattr(
        library_controller.tv_channels,
        "add_custom_channels",
        lambda channels: calls.append(("add_custom_channels", channels)),
    )
    monkeypatch.setattr(
        library_controller,
        "QMessageBox",
        SimpleNamespace(
            warning=lambda *args: calls.append(("warning", args)),
            information=lambda *args: calls.append(("information", args)),
        ),
    )
    window = SimpleNamespace(
        _is_closing=True,
        tv_channels_data=original_channels,
        radio_stations_data=[],
        lists=SimpleNamespace(
            refresh_group_filter=lambda: calls.append(("refresh_group_filter",)),
            populate_tv_list=lambda channels: calls.append(
                ("populate_tv_list", channels)
            ),
        ),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda *args: calls.append(("showMessage", args))
        ),
    )
    controller = SimpleNamespace(win=window)

    library_controller.LibraryController._on_playlist_fetched(
        controller,
        [queued_channel],
        "tv",
    )

    assert window.tv_channels_data is original_channels
    assert window.tv_channels_data == [original_channels[0]]
    assert calls == []


def test_playlist_result_updates_owner_when_not_closing(monkeypatch):
    from ui import library_controller

    calls = []
    queued_channel = SimpleNamespace(
        name="Queued",
        url="https://example.invalid/stream",
        logo="",
        group="Imported",
        tvg_id="queued-id",
    )
    monkeypatch.setattr(
        library_controller.tv_channels,
        "add_custom_channels",
        lambda channels: calls.append(("add_custom_channels", channels)),
    )
    monkeypatch.setattr(
        library_controller,
        "QMessageBox",
        SimpleNamespace(
            warning=lambda *args: calls.append(("warning", args)),
            information=lambda *args: calls.append(("information", args)),
        ),
    )
    window = SimpleNamespace(
        _is_closing=False,
        tv_channels_data=[],
        radio_stations_data=[],
        lists=SimpleNamespace(
            refresh_group_filter=lambda: calls.append(("refresh_group_filter",)),
            populate_tv_list=lambda channels: calls.append(
                ("populate_tv_list", channels)
            ),
        ),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda *args: calls.append(("showMessage", args))
        ),
    )
    controller = SimpleNamespace(win=window)

    library_controller.LibraryController._on_playlist_fetched(
        controller,
        [queued_channel],
        "tv",
    )

    assert window.tv_channels_data == [queued_channel]
    assert ("add_custom_channels", [queued_channel]) in calls
    assert ("refresh_group_filter",) in calls
    assert ("populate_tv_list", window.tv_channels_data) in calls
    assert any(call[0] == "showMessage" for call in calls)
    assert any(call[0] == "information" for call in calls)


def test_podcast_result_does_not_mutate_panel_while_owner_is_closing():
    from ui.podcast_panel import PodcastPanel

    calls = []
    owner = SimpleNamespace(_is_closing=True)
    panel = SimpleNamespace(
        window=lambda: owner,
        status_label=SimpleNamespace(
            setText=lambda text: calls.append(("setText", text))
        ),
        _add_episode_row=lambda episode: calls.append(("add_episode_row", episode)),
    )

    PodcastPanel._on_episodes_loaded(panel, ["queued episode"])

    assert calls == []


def test_podcast_result_updates_panel_when_owner_is_not_closing():
    from ui.podcast_panel import PodcastPanel

    calls = []
    owner = SimpleNamespace()
    panel = SimpleNamespace(
        window=lambda: owner,
        status_label=SimpleNamespace(
            setText=lambda text: calls.append(("setText", text))
        ),
        _add_episode_row=lambda episode: calls.append(("add_episode_row", episode)),
    )

    PodcastPanel._on_episodes_loaded(panel, ["loaded episode"])

    assert calls == [
        ("setText", "1 episodios."),
        ("add_episode_row", "loaded episode"),
    ]

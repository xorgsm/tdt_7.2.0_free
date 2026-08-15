"""
Pruebas de core/recording_schedule.py: check_starts_due() debe pasar a
"recording" solo las pendientes cuya hora de inicio ya llegó (con margen
de tolerancia), marcar "error" las que se pasaron de largo (la app
estuvo cerrada más tiempo del margen), y dejar intactas las que aún no
tocan. check_stops_due() debe devolver las que llevan grabando y ya
llegó su hora de fin.
"""
from datetime import datetime, timedelta

from core.recording_schedule import (
    ScheduledRecording,
    add_scheduled,
    check_starts_due,
    check_stops_due,
    has_scheduled,
    load_scheduled,
    mark_done,
    mark_error,
    remove_scheduled,
)

FORMATO = "%Y%m%d%H%M%S"


def _fmt(dt: datetime) -> str:
    return dt.strftime(FORMATO)


def _parse_time_fn(s: str):
    try:
        return datetime.strptime(s, FORMATO)
    except ValueError:
        return None


def _rec(**overrides):
    ahora = _fmt(datetime.now())
    base = dict(
        tvg_id="la1", channel_name="La 1", channel_url="http://stream",
        title="Telediario", start=ahora, stop=ahora,
    )
    base.update(overrides)
    return ScheduledRecording(**base)


def test_add_scheduled_no_duplica_la_misma_grabacion():
    r = _rec()
    add_scheduled(r)
    add_scheduled(r)
    assert len(load_scheduled()) == 1


def test_has_scheduled():
    r = _rec()
    add_scheduled(r)
    assert has_scheduled("la1", "Telediario", r.start) is True
    assert has_scheduled("la1", "Otro", r.start) is False


def test_remove_scheduled():
    r = _rec()
    add_scheduled(r)
    restante = remove_scheduled("la1", "Telediario", r.start)
    assert restante == []


def test_check_starts_due_pasa_a_recording_la_que_ya_toca():
    inicio = datetime.now() - timedelta(minutes=3)
    r = _rec(start=_fmt(inicio))
    add_scheduled(r)

    arrancadas = check_starts_due(_parse_time_fn)

    assert len(arrancadas) == 1
    assert arrancadas[0].status == "recording"
    assert load_scheduled()[0].status == "recording"


def test_check_starts_due_no_toca_la_que_aun_no_llega():
    futuro = datetime.now() + timedelta(hours=1)
    r = _rec(start=_fmt(futuro))
    add_scheduled(r)

    arrancadas = check_starts_due(_parse_time_fn)

    assert arrancadas == []
    assert load_scheduled()[0].status == "pending"


def test_check_starts_due_marca_error_si_se_paso_de_largo():
    hace_mucho = datetime.now() - timedelta(hours=1)
    r = _rec(start=_fmt(hace_mucho))
    add_scheduled(r)

    arrancadas = check_starts_due(_parse_time_fn)

    assert arrancadas == []
    assert load_scheduled()[0].status == "error"


def test_check_starts_due_ignora_las_que_no_estan_pending():
    r = _rec(status="recording")
    add_scheduled(r)

    arrancadas = check_starts_due(_parse_time_fn)

    assert arrancadas == []


def test_check_stops_due_devuelve_la_que_ya_debe_parar():
    fin = datetime.now() - timedelta(minutes=1)
    r = _rec(status="recording", stop=_fmt(fin))
    add_scheduled(r)

    a_parar = check_stops_due(_parse_time_fn)

    assert len(a_parar) == 1


def test_check_stops_due_no_incluye_la_que_aun_no_termina():
    fin = datetime.now() + timedelta(hours=1)
    r = _rec(status="recording", stop=_fmt(fin))
    add_scheduled(r)

    a_parar = check_stops_due(_parse_time_fn)

    assert a_parar == []


def test_mark_done_quita_la_entrada():
    r = _rec()
    add_scheduled(r)
    mark_done("la1", "Telediario", r.start)
    assert load_scheduled() == []


def test_mark_error_deja_la_entrada_visible_como_error():
    r = _rec()
    add_scheduled(r)
    mark_error("la1", "Telediario", r.start)

    pendiente = load_scheduled()[0]
    assert pendiente.status == "error"

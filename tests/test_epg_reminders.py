"""
Pruebas de core/epg_reminders.py: check_due() debe disparar solo los
avisos cuya hora de inicio ya llegó (con margen de tolerancia hacia
atrás) y quitarlos de la lista de pendientes; los que aún no tocan se
quedan, y los que llevan demasiado tiempo pasados se descartan sin
avisar (para no lanzar un aviso de algo que empezó hace horas).
"""
from datetime import datetime, timedelta

from core.epg_reminders import (
    Reminder,
    add_reminder,
    check_due,
    has_reminder,
    load_reminders,
    remove_reminder,
)

FORMATO = "%Y%m%d%H%M%S"


def _fmt(dt: datetime) -> str:
    return dt.strftime(FORMATO)


def _parse_time_fn(s: str):
    try:
        return datetime.strptime(s, FORMATO)
    except ValueError:
        return None


def test_add_reminder_no_duplica_el_mismo_aviso():
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Telediario", start="20260815200000")
    add_reminder(r)
    add_reminder(r)

    assert len(load_reminders()) == 1


def test_has_reminder():
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Telediario", start="20260815200000")
    add_reminder(r)
    assert has_reminder("la1", "Telediario", "20260815200000") is True
    assert has_reminder("la1", "Otro", "20260815200000") is False


def test_remove_reminder():
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Telediario", start="20260815200000")
    add_reminder(r)
    restante = remove_reminder("la1", "Telediario", "20260815200000")
    assert restante == []


def test_check_due_dispara_el_que_ya_toca_y_lo_quita_de_pendientes():
    hace_5_min = datetime.now() - timedelta(minutes=5)
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Telediario", start=_fmt(hace_5_min))
    add_reminder(r)

    disparados = check_due(_parse_time_fn)

    assert len(disparados) == 1
    assert disparados[0].title == "Telediario"
    assert load_reminders() == []


def test_check_due_no_dispara_el_que_aun_no_toca():
    futuro = datetime.now() + timedelta(hours=2)
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Cine", start=_fmt(futuro))
    add_reminder(r)

    disparados = check_due(_parse_time_fn)

    assert disparados == []
    assert len(load_reminders()) == 1


def test_check_due_descarta_sin_avisar_si_paso_mucho_tiempo():
    hace_una_hora = datetime.now() - timedelta(hours=1)
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Viejo", start=_fmt(hace_una_hora))
    add_reminder(r)

    disparados = check_due(_parse_time_fn)

    assert disparados == []
    assert load_reminders() == []  # se descarta, no se queda pendiente para siempre


def test_check_due_ignora_hora_corrupta():
    r = Reminder(tvg_id="la1", channel_name="La 1", title="Corrupto", start="no-es-una-fecha")
    add_reminder(r)

    disparados = check_due(_parse_time_fn)

    assert disparados == []

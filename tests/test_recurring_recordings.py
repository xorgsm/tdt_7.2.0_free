"""
Pruebas de core/recurring_recordings.py: una regla que toca hoy debe
insertarse una vez en core.recording_schedule, y no reinsertarse si se
vuelve a sincronizar el mismo día (incluso después de mark_done, que
simula que la grabación ya terminó).
"""
from datetime import datetime

import json
import pytest

from core import recording_schedule
from core import recurring_recordings
from core.recurring_recordings import add_rule, load_rules, sync_into_schedule


def _lunes_10_00():
    """Un lunes cualquiera a las 10:00 -- weekday()==0."""
    return datetime(2026, 8, 3, 10, 0)  # 2026-08-03 es lunes


def test_sync_inserta_regla_que_toca_hoy():
    add_rule("La 1", "http://stream", days=[0], start_time="09:30", duration_minutes=30)

    sync_into_schedule(now=_lunes_10_00())

    pendientes = recording_schedule.load_scheduled()
    assert len(pendientes) == 1
    assert pendientes[0].channel_name == "La 1"
    assert pendientes[0].tvg_id.startswith("recurring:")


def test_sync_no_duplica_si_se_llama_varias_veces_el_mismo_dia():
    add_rule("La 1", "http://stream", days=[0], start_time="09:30", duration_minutes=30)

    sync_into_schedule(now=_lunes_10_00())
    sync_into_schedule(now=_lunes_10_00())
    sync_into_schedule(now=datetime(2026, 8, 3, 10, 5))

    assert len(recording_schedule.load_scheduled()) == 1


def test_sync_no_reinserta_tras_mark_done_el_mismo_dia():
    add_rule("La 1", "http://stream", days=[0], start_time="09:30", duration_minutes=30)
    sync_into_schedule(now=_lunes_10_00())

    pendiente = recording_schedule.load_scheduled()[0]
    recording_schedule.mark_done(pendiente.tvg_id, pendiente.title, pendiente.start)
    assert recording_schedule.load_scheduled() == []

    # Aunque se vuelva a comprobar más tarde ese mismo día, no debe reaparecer.
    sync_into_schedule(now=datetime(2026, 8, 3, 12, 0))
    assert recording_schedule.load_scheduled() == []


def test_sync_ignora_dia_que_no_toca():
    add_rule("La 1", "http://stream", days=[1], start_time="09:30", duration_minutes=30)  # martes

    sync_into_schedule(now=_lunes_10_00())  # es lunes

    assert recording_schedule.load_scheduled() == []


def test_sync_ignora_regla_deshabilitada():
    from core.recurring_recordings import set_rule_enabled

    rule = add_rule("La 1", "http://stream", days=[0], start_time="09:30", duration_minutes=30)
    set_rule_enabled(rule.id, False)

    sync_into_schedule(now=_lunes_10_00())

    assert recording_schedule.load_scheduled() == []


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("start_time", "25:00"),
        ("start_time", "12:60"),
        ("start_time", "9:30"),
        ("start_time", "texto"),
        ("days", []),
        ("days", [-1]),
        ("days", [7]),
        ("days", ["0"]),
        ("duration_minutes", 0),
        ("duration_minutes", -1),
        ("duration_minutes", 1.5),
        ("duration_minutes", "30"),
        ("channel_name", ""),
        ("channel_url", ""),
    ],
)
def test_add_rule_rechaza_entradas_invalidas(campo, valor):
    argumentos = {
        "channel_name": "La 1",
        "channel_url": "http://stream",
        "days": [0],
        "start_time": "09:30",
        "duration_minutes": 30,
    }
    argumentos[campo] = valor

    with pytest.raises(ValueError):
        add_rule(**argumentos)


def test_add_rule_rechaza_hora_con_digitos_no_ascii():
    with pytest.raises(ValueError, match="hora"):
        add_rule(
            "La 1",
            "http://stream",
            days=[0],
            start_time="0٩:3٠",
            duration_minutes=30,
        )


def test_add_rule_rechaza_duracion_superior_al_limite_de_la_ui():
    with pytest.raises(ValueError, match="duración"):
        add_rule(
            "La 1",
            "http://stream",
            days=[0],
            start_time="09:30",
            duration_minutes=601,
        )


def test_set_rule_enabled_rechaza_no_bool_sin_mutar_ni_persistir():
    rule = add_rule(
        "La 1",
        "http://stream",
        days=[0],
        start_time="09:30",
        duration_minutes=30,
    )
    before = recurring_recordings._rules_path().read_bytes()

    with pytest.raises(ValueError, match="estado"):
        recurring_recordings.set_rule_enabled(rule.id, 1)

    assert recurring_recordings._rules_path().read_bytes() == before
    assert load_rules()[0].enabled is True


def test_sync_ignora_overflow_de_una_regla_y_procesa_la_valida_posterior(
    monkeypatch,
):
    enorme = recurring_recordings.RecurringRule(
        id="enorme",
        channel_name="Canal enorme",
        channel_url="http://stream-enorme",
        days=[0],
        start_time="09:00",
        duration_minutes=10**100,
    )
    valida = recurring_recordings.RecurringRule(
        id="valida-posterior",
        channel_name="Canal válido",
        channel_url="http://stream-valido",
        days=[0],
        start_time="09:30",
        duration_minutes=30,
    )
    monkeypatch.setattr(recurring_recordings, "load_rules", lambda: [enorme, valida])

    sync_into_schedule(now=_lunes_10_00())

    pendientes = recording_schedule.load_scheduled()
    assert [pendiente.tvg_id for pendiente in pendientes] == [
        "recurring:valida-posterior"
    ]


def test_load_rules_descarta_regla_persistida_invalida_y_sync_solo_valida():
    reglas = [
        {
            "id": "invalida",
            "channel_name": "La 1",
            "channel_url": "http://stream",
            "days": [0],
            "start_time": "25:00",
            "duration_minutes": 30,
            "enabled": True,
        },
        {
            "id": "valida",
            "channel_name": "La 2",
            "channel_url": "http://stream-2",
            "days": [0],
            "start_time": "09:30",
            "duration_minutes": 30,
            "enabled": True,
        },
    ]
    recurring_recordings._rules_path().write_text(
        json.dumps(reglas), encoding="utf-8"
    )

    cargadas = load_rules()
    sync_into_schedule(now=_lunes_10_00())

    assert [regla.id for regla in cargadas] == ["valida"]
    assert len(recording_schedule.load_scheduled()) == 1
    assert recording_schedule.load_scheduled()[0].tvg_id == "recurring:valida"


def test_save_rules_propaga_error_de_escritura_atomica(monkeypatch):
    """Rompería si un guardado de reglas fallido se ocultara al flujo interno."""
    def fail_write(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(recurring_recordings, "write_json_atomic", fail_write)

    with pytest.raises(OSError, match="disco lleno"):
        recurring_recordings._save_rules([])


def test_save_sync_state_propaga_error_de_escritura_atomica(monkeypatch):
    """Rompería si un guardado de estado fallido se ocultara al sincronizador."""
    def fail_write(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(recurring_recordings, "write_json_atomic", fail_write)

    with pytest.raises(OSError, match="disco lleno"):
        recurring_recordings._save_sync_state({"regla": "20260803"})

"""
Reglas de grabación recurrente: "todos los [días de la semana] a las
[hora], durante [minutos] minutos, en [canal]" -- independientes de la
guía EPG (útiles para canales sin EPG, o cuando lo que importa es la
hora exacta y no lo que diga la programación).

Se apoyan en el mismo mecanismo que ya existe para las grabaciones
programadas desde la EPG (core/recording_schedule.py): cada vez que se
sincronizan (ver sync_into_schedule), a cada regla que toque hoy y no se
haya insertado ya se le crea una ScheduledRecording concreta para HOY --
a partir de ahí, arrancar, parar, reintentar y avisar por bandeja lo hace
el mismo código ya existente y probado (ui/tray_controller.py), sin
duplicar esa lógica aquí.

Coder By X@R
"""
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from core import recording_schedule
from core.config import get_profile_data_dir
from core.json_store import read_json, write_json_atomic

RULES_FILE = "recurring_recordings.json"
SYNC_STATE_FILE = "recurring_recordings_sync.json"
MAX_DURATION_MINUTES = 600

DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


@dataclass
class RecurringRule:
    id: str
    channel_name: str
    channel_url: str
    days: List[int] = field(default_factory=list)  # 0=lunes ... 6=domingo (datetime.weekday())
    start_time: str = "20:00"  # "HH:MM"
    duration_minutes: int = 60
    enabled: bool = True


def _rules_path():
    # Por perfil, como recording_schedule.py (que ya inserta las grabaciones
    # concretas de cada regla ahí) -- antes vivían en get_app_data_dir()
    # (global), así que una regla creada en un perfil se sincronizaba
    # también en la sesión de cualquier otro. El perfil "Default" ES
    # get_app_data_dir() (ver core/config.py), así que quien no usa
    # perfiles adicionales no nota ningún cambio: sus reglas ya estaban ahí.
    return get_profile_data_dir() / RULES_FILE


def _sync_path():
    return get_profile_data_dir() / SYNC_STATE_FILE


def _validate_rule(rule: RecurringRule) -> None:
    if not isinstance(rule, RecurringRule):
        raise ValueError("la regla debe ser RecurringRule")
    if type(rule.id) is not str:
        raise ValueError("id inválido")
    if type(rule.channel_name) is not str or not rule.channel_name.strip():
        raise ValueError("nombre de canal vacío o inválido")
    if type(rule.channel_url) is not str or not rule.channel_url.strip():
        raise ValueError("URL de canal vacía o inválida")
    if type(rule.days) is not list or not rule.days:
        raise ValueError("días inválidos")
    if any(type(day) is not int or not 0 <= day <= 6 for day in rule.days):
        raise ValueError("días inválidos")
    if type(rule.start_time) is not str or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", rule.start_time
    ):
        raise ValueError("hora inválida")
    if (
        type(rule.duration_minutes) is not int
        or not 1 <= rule.duration_minutes <= MAX_DURATION_MINUTES
    ):
        raise ValueError("duración inválida")
    if type(rule.enabled) is not bool:
        raise ValueError("estado inválido")


def load_rules() -> List[RecurringRule]:
    data = read_json(_rules_path(), [])
    if not isinstance(data, list):
        return []
    resultado = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            rule = RecurringRule(**item)
            _validate_rule(rule)
            resultado.append(rule)
        except (TypeError, ValueError):
            continue  # entrada con campos que no encajan; se descarta sola
    return resultado


def _save_rules(rules: List[RecurringRule]) -> None:
    write_json_atomic(_rules_path(), [asdict(r) for r in rules], indent=2)


def add_rule(channel_name: str, channel_url: str, days: List[int], start_time: str,
             duration_minutes: int) -> RecurringRule:
    rule = RecurringRule(
        id=uuid.uuid4().hex[:12],
        channel_name=channel_name,
        channel_url=channel_url,
        days=days,
        start_time=start_time,
        duration_minutes=duration_minutes,
    )
    _validate_rule(rule)
    rule.days = sorted(set(rule.days))
    rules = load_rules()
    rules.append(rule)
    _save_rules(rules)
    return rule


def remove_rule(rule_id: str) -> List[RecurringRule]:
    rules = [r for r in load_rules() if r.id != rule_id]
    _save_rules(rules)
    return rules


def set_rule_enabled(rule_id: str, enabled: bool) -> List[RecurringRule]:
    if type(enabled) is not bool:
        raise ValueError("estado inválido")
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            r.enabled = enabled
    _save_rules(rules)
    return rules


def _load_sync_state() -> dict:
    data = read_json(_sync_path(), {})
    return data if isinstance(data, dict) else {}


def _save_sync_state(state: dict) -> None:
    write_json_atomic(_sync_path(), state)


def sync_into_schedule(now: Optional[datetime] = None) -> None:
    """
    Para cada regla habilitada cuyo día de la semana sea hoy y que todavía
    no se haya sincronizado hoy, crea su ScheduledRecording concreta de
    hoy en core.recording_schedule. Se apoya en un pequeño archivo de
    estado (qué regla ya se sincronizó en qué fecha) para no reinsertarla
    en cada comprobación del día -- sin esto, cada ciclo del timer de 30s
    (ver ui/tray_controller.py) volvería a añadirla justo después de que
    mark_done() la quitara al terminar.

    Pensado para llamarse desde ese mismo timer periódico: es barato
    (solo compara fechas en memoria) y no hace nada si ninguna regla toca
    todavía hoy.
    """
    now = now or datetime.now()
    hoy = now.date()
    hoy_str = hoy.strftime("%Y%m%d")
    estado = _load_sync_state()
    cambiado = False

    for rule in load_rules():
        if not rule.enabled or now.weekday() not in rule.days:
            continue
        if estado.get(rule.id) == hoy_str:
            continue  # ya se insertó hoy para esta regla

        try:
            hora, minuto = (int(p) for p in rule.start_time.split(":"))
            inicio = datetime.combine(hoy, datetime.min.time()).replace(hour=hora, minute=minuto)
            fin = inicio + timedelta(minutes=rule.duration_minutes)
        except (ValueError, OverflowError):
            continue  # una regla inválida no impide procesar las siguientes

        recording_schedule.add_scheduled(recording_schedule.ScheduledRecording(
            tvg_id=f"recurring:{rule.id}",
            channel_name=rule.channel_name,
            channel_url=rule.channel_url,
            title=f"Grabación recurrente: {rule.channel_name}",
            start=inicio.strftime("%Y%m%d%H%M%S"),
            stop=fin.strftime("%Y%m%d%H%M%S"),
        ))
        estado[rule.id] = hoy_str
        cambiado = True

    if cambiado:
        _save_sync_state(estado)

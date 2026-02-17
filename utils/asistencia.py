import datetime

from repositories.asistencia_repository import create_ausente, exists_for_empleado_fecha
from repositories.empleado_excepcion_repository import get_by_empleado_fecha as get_excepcion_by_empleado_fecha
from repositories.empleado_horario_repository import (
    get_by_empleado_fecha,
    get_empleados_activos_en_fecha,
)
from repositories.excepcion_bloque_repository import get_by_excepcion as get_excepcion_bloques
from repositories.horario_dia_bloque_repository import get_by_horario_dia as get_bloques_by_horario_dia
from repositories.horario_dia_repository import get_by_horario as get_dias_by_horario


def _to_minutes(value):
    if not value:
        return None
    try:
        if isinstance(value, datetime.time):
            return value.hour * 60 + value.minute
        if isinstance(value, datetime.timedelta):
            return int(value.total_seconds() // 60)
        t = datetime.time.fromisoformat(str(value))
        return t.hour * 60 + t.minute
    except (ValueError, TypeError):
        return None


def _format_hhmm(value):
    if isinstance(value, datetime.timedelta):
        total_minutes = int(value.total_seconds() // 60)
        hours = (total_minutes // 60) % 24
        minutes = total_minutes % 60
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value or "").strip()
    if not text:
        return text
    try:
        parsed = datetime.time.fromisoformat(text)
        return parsed.strftime("%H:%M")
    except ValueError:
        pass
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    if len(text) >= 5:
        return text[:5]
    return text


def _tipo_anula(tipo: str | None):
    if not tipo:
        return False
    return tipo.upper() in {"FRANCO", "VACACIONES", "FERIADO", "LICENCIA"}


def _is_within_blocks(blocks, minutes):
    for b in blocks:
        start = _to_minutes(b.get("entrada"))
        end = _to_minutes(b.get("salida"))
        if start is None or end is None:
            continue
        if minutes >= start and minutes <= end:
            return True, start, end
    return False, None, None


def _match_day(dias, fecha):
    if not dias:
        return True
    values = [d.get("dia_semana") for d in dias if d.get("dia_semana") is not None]
    if not values:
        return True
    return fecha.isoweekday() in values


def _find_dia_row(dias, fecha):
    target = fecha.isoweekday()
    for d in dias:
        if d.get("dia_semana") == target:
            return d
    return None


def _build_blocks(rows):
    blocks = []
    for b in rows or []:
        blocks.append({
            "entrada": _format_hhmm(b.get("hora_entrada")),
            "salida": _format_hhmm(b.get("hora_salida")),
        })
    return blocks


def infer_estado(hora_entrada, hora_salida, bloques, tolerancia_min):
    estado = None
    entrada_min = _to_minutes(hora_entrada)
    salida_min = _to_minutes(hora_salida)

    if entrada_min is not None and bloques:
        ok, start, _ = _is_within_blocks(bloques, entrada_min)
        if ok:
            limite = start + (tolerancia_min or 0)
            estado = "tarde" if entrada_min > limite else "ok"

    if salida_min is not None and bloques:
        ok, _, end = _is_within_blocks(bloques, salida_min)
        if ok and end is not None and salida_min < end:
            estado = "salida_anticipada"

    return estado


def get_horario_esperado(empleado_id: int, fecha_str: str):
    fecha = datetime.date.fromisoformat(fecha_str)

    excepcion = get_excepcion_by_empleado_fecha(empleado_id, fecha_str)
    if excepcion:
        bloques_ex = _build_blocks(get_excepcion_bloques(excepcion["id"]))
        anula = bool(excepcion.get("anula_horario")) or _tipo_anula(excepcion.get("tipo"))

        if anula:
            return {
                "tiene_excepcion": True,
                "tipo_excepcion": excepcion.get("tipo"),
                "anula_horario": True,
                "bloques": bloques_ex,
                "tolerancia": 0,
            }

        if (excepcion.get("tipo") or "").upper() == "CAMBIO_HORARIO":
            horario_base = get_by_empleado_fecha(empleado_id, fecha_str)
            tolerancia = int(horario_base.get("tolerancia_min") or 0) if horario_base else 0
            return {
                "tiene_excepcion": True,
                "tipo_excepcion": excepcion.get("tipo"),
                "anula_horario": False,
                "bloques": bloques_ex,
                "tolerancia": tolerancia,
            }

    horario = get_by_empleado_fecha(empleado_id, fecha_str)
    if not horario:
        return None

    dias = get_dias_by_horario(horario["horario_id"])
    if not _match_day(dias, fecha):
        return {
            "tiene_excepcion": bool(excepcion),
            "tipo_excepcion": excepcion.get("tipo") if excepcion else None,
            "anula_horario": False,
            "bloques": [],
            "tolerancia": int(horario.get("tolerancia_min") or 0),
        }

    dia_row = _find_dia_row(dias, fecha)
    bloques = []
    if dia_row:
        bloques = _build_blocks(get_bloques_by_horario_dia(dia_row["id"]))

    return {
        "tiene_excepcion": bool(excepcion),
        "tipo_excepcion": excepcion.get("tipo") if excepcion else None,
        "anula_horario": False,
        "bloques": bloques,
        "tolerancia": int(horario.get("tolerancia_min") or 0),
    }


def validar_asistencia(empleado_id: int | None, fecha_str: str, hora_entrada: str | None, hora_salida: str | None):
    errors = []
    if not empleado_id or not fecha_str:
        return errors, None

    try:
        esperado = get_horario_esperado(empleado_id, fecha_str)
    except ValueError:
        errors.append("Fecha invalida.")
        return errors, None

    if not esperado:
        errors.append("Empleado sin horario asignado para esa fecha.")
        return errors, None

    bloques = esperado.get("bloques") or []
    if esperado.get("anula_horario") and not bloques:
        return errors, None

    entrada_min = _to_minutes(hora_entrada)
    salida_min = _to_minutes(hora_salida)

    if bloques:
        if entrada_min is not None:
            ok, _, _ = _is_within_blocks(bloques, entrada_min)
            if not ok:
                errors.append("Hora de entrada fuera de bloques esperados.")
        if salida_min is not None:
            ok, _, _ = _is_within_blocks(bloques, salida_min)
            if not ok:
                errors.append("Hora de salida fuera de bloques esperados.")

    estado = infer_estado(hora_entrada, hora_salida, bloques, esperado.get("tolerancia", 0))
    if estado is None and not hora_entrada and not hora_salida:
        estado = "ausente"
    return errors, estado


def generar_ausentes(fecha_str: str):
    try:
        datetime.date.fromisoformat(fecha_str)
    except ValueError:
        return 0, ["Fecha invalida."]

    registros = get_empleados_activos_en_fecha(fecha_str)
    ausentes = 0
    errors = []

    for reg in registros:
        empleado_id = reg.get("empleado_id")
        if not empleado_id:
            continue
        if exists_for_empleado_fecha(empleado_id, fecha_str):
            continue

        try:
            esperado = get_horario_esperado(empleado_id, fecha_str)
        except ValueError:
            continue
        if not esperado:
            continue
        if esperado.get("anula_horario") and not esperado.get("bloques"):
            continue
        if not esperado.get("bloques"):
            continue

        create_ausente(empleado_id, fecha_str, "Ausente auto")
        ausentes += 1

    return ausentes, errors

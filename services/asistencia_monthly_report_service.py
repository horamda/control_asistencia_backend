from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo


def _date_iso(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "").strip()


def _time_to_minutes(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds() // 60)
    if hasattr(value, "hour"):
        return int(value.hour) * 60 + int(value.minute)
    parts = str(value).split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (TypeError, ValueError):
        return None


def _worked_day(marks):
    """Sum closed pairs; duplicates and unmatched punches remain incomplete."""
    ordered = sorted(marks, key=lambda m: (_time_to_minutes(m.get("hora")) or 0, int(m.get("id") or 0)))
    entry = None
    minutes = 0
    pairs = 0
    incomplete = False
    for mark in ordered:
        value = _time_to_minutes(mark.get("hora"))
        action = str(mark.get("accion") or "").lower()
        if value is None or action not in {"ingreso", "egreso"}:
            incomplete = True
        elif action == "ingreso":
            if entry is not None:
                incomplete = True
            else:
                entry = value
        elif entry is None:
            incomplete = True
        else:
            minutes += value - entry
            pairs += 1
            entry = None
    return (round(minutes / 60, 2) if pairs else None, incomplete or entry is not None, entry is not None)


def _employment_date(value):
    return dt.date.fromisoformat(str(value)[:10]) if value else None


def _employment_periods(emp: dict) -> list[tuple]:
    """Periodos trabajados [(desde, hasta)] con None como extremo abierto.

    Si el empleado trae "periodos_laborales" (bajas y reingresos) se usan esos;
    si no, el unico periodo fecha_ingreso..fecha_baja de los inactivos con baja
    y de los activos.
    """
    if "periodos_laborales" in emp:
        return [(_employment_date(desde), _employment_date(hasta)) for desde, hasta in emp["periodos_laborales"] or []]
    if int(emp.get("activo") or 0) != 1 and _employment_date(emp.get("fecha_baja")) is None:
        return []
    return [(_employment_date(emp.get("fecha_ingreso")), _employment_date(emp.get("fecha_baja")))]


def _employed_on(periods: list[tuple], day: dt.date) -> bool:
    return any((desde is None or desde <= day) and (hasta is None or hasta >= day) for desde, hasta in periods)


def _employee_name(row: dict) -> str:
    return " ".join(
        part.strip()
        for part in [str(row.get("apellido") or ""), str(row.get("nombre") or "")]
        if part and part.strip()
    )


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def parse_month(value: str | None, *, today: dt.date | None = None) -> tuple[int, int]:
    today = today or dt.date.today()
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = dt.date.fromisoformat(f"{raw}-01")
            return parsed.year, parsed.month
        except ValueError:
            pass
    return today.year, today.month


def parse_non_laborable_days(raw: str | None, *, year: int, month: int) -> set[str]:
    days = set()
    _, last = month_bounds(year, month)
    last_day = last.day
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= last_day:
            days.add(dt.date(year, month, day).isoformat())
    return days


def build_monthly_attendance_report(
    *,
    year: int,
    month: int,
    empleados: list[dict],
    marcas: list[dict],
    justificaciones: list[dict],
    vacaciones: list[dict] | None = None,
    non_laborable_days: set[str] | None = None,
    today: dt.date | None = None,
) -> dict:
    today = today or dt.datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    first, last = month_bounds(year, month)
    month_dates = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    non_laborable_days = set(non_laborable_days or set())
    for day in month_dates:
        if day.weekday() == 6:
            non_laborable_days.add(day.isoformat())

    # Today's absence cannot be decided until the day has ended.
    laborable_dates = [day for day in month_dates if day < today and day.isoformat() not in non_laborable_days]
    laborable_set = {d.isoformat() for d in laborable_dates}
    periods_by_emp = {id(e): _employment_periods(e) for e in empleados}
    empleados_activos = [
        e
        for e in empleados
        if any((desde or first) <= last and (hasta or last) >= first for desde, hasta in periods_by_emp[id(e)])
        and int(e.get("requiere_control_asistencia", 1) or 0) == 1
    ]
    empleado_ids = {int(e["id"]) for e in empleados_activos if e.get("id")}

    marcas_by_emp_day = defaultdict(list)
    jornada_rows = []
    registros_mes = 0
    for marca in marcas or []:
        empleado_id = int(marca.get("empleado_id") or 0)
        fecha = _date_iso(marca.get("fecha"))
        if empleado_id not in empleado_ids or not (first.isoformat() <= fecha <= min(last, today).isoformat()):
            continue
        registros_mes += 1
        marcas_by_emp_day[(empleado_id, fecha)].append(marca)

    just_by_emp_day = defaultdict(list)
    for just in justificaciones or []:
        empleado_id = int(just.get("empleado_id") or 0)
        if empleado_id not in empleado_ids:
            continue
        estado = str(just.get("estado") or "").strip().lower()
        if estado != "aprobada":
            continue
        desde = dt.date.fromisoformat(_date_iso(just.get("fecha_desde") or just.get("fecha")))
        hasta = dt.date.fromisoformat(_date_iso(just.get("fecha_hasta") or just.get("fecha")))
        current = max(desde, first)
        until = min(hasta, last)
        while current <= until:
            just_by_emp_day[(empleado_id, current.isoformat())].append(just)
            current += dt.timedelta(days=1)

    vacation_by_emp_day = defaultdict(list)
    for vac in vacaciones or []:
        empleado_id = int(vac.get("empleado_id") or 0)
        if empleado_id not in empleado_ids:
            continue
        tipo = str(vac.get("tipo") or "").strip().lower()
        estado = str(vac.get("estado") or "").strip().lower()
        if tipo != "tomado" or estado != "aprobado":
            continue
        if vac.get("revertido_por_movimiento_id") or vac.get("origen_movimiento_id"):
            continue
        desde = dt.date.fromisoformat(_date_iso(vac.get("fecha_desde")))
        hasta = dt.date.fromisoformat(_date_iso(vac.get("fecha_hasta")))
        current = max(desde, first)
        until = min(hasta, last)
        while current <= until:
            vacation_by_emp_day[(empleado_id, current.isoformat())].append(vac)
            current += dt.timedelta(days=1)

    resumen_rows = []
    ausencias_rows = []
    analisis_sector = defaultdict(lambda: {"sector": None, "empleados": 0, "ausencias": 0, "justificadas": 0, "posibles": 0})
    total_ausencias = 0
    total_justificadas = 0
    total_presentes = 0
    total_vacaciones = 0
    total_fichajes_incompletos = 0
    total_horas_trabajadas = 0.0
    jornadas_mayores_12 = 0
    sin_egreso = 0
    planilla_rows = []

    for emp in empleados_activos:
        empleado_id = int(emp["id"])
        nombre = _employee_name(emp)
        sector = emp.get("sector_nombre") or "Sin sector"
        analisis_sector[sector]["sector"] = sector
        analisis_sector[sector]["empleados"] += 1

        presentes = 0
        aus_comp = 0
        aus_just = 0
        vacaciones_count = 0
        incompletos_count = 0
        horas_count = 0.0
        cells = []
        periods = periods_by_emp[id(emp)]
        posible = sum(_employed_on(periods, day) for day in laborable_dates)
        analisis_sector[sector]["posibles"] += posible
        for day in month_dates:
            fecha = day.isoformat()
            day_marcas = marcas_by_emp_day.get((empleado_id, fecha), [])
            justificada = bool(just_by_emp_day.get((empleado_id, fecha)))
            en_vacaciones = bool(vacation_by_emp_day.get((empleado_id, fecha)))
            is_laborable = fecha in laborable_set
            hours, incomplete, missing_exit = _worked_day(day_marcas)
            if not _employed_on(periods, day):
                cells.append({"iso": fecha, "day": day.day, "status": "outside", "label": "—", "title": "Fuera del periodo laboral", "hours": None})
                continue
            if hours is not None:
                total_horas_trabajadas += hours
                horas_count += hours
            if day_marcas:
                estado = "Fichaje incompleto" if incomplete else "Normal"
                if missing_exit:
                    sin_egreso += 1
                    estado = "Sin egreso"
                elif hours is not None and hours > 12:
                    jornadas_mayores_12 += 1
                    estado = "> 12 hs"
                jornada_rows.append({"fecha": fecha, "empleado": nombre, "sector": sector, "horas": hours, "estado": estado})
            if day >= today:
                cells.append({"iso": fecha, "day": day.day, "status": "pending", "label": "Hoy" if day == today else "—", "title": "Dia en curso, excluido del indice" if day == today else "Dia futuro, sin evaluar", "hours": hours})
                continue
            if not is_laborable:
                cell = {"iso": fecha, "day": day.day, "status": "non_laborable", "label": "NL", "title": "No laborable", "hours": hours}
            elif day_marcas:
                presentes += 1
                if incomplete:
                    incompletos_count += 1
                    total_fichajes_incompletos += 1
                    cell = {"iso": fecha, "day": day.day, "status": "incomplete", "label": "FI", "title": "Fichaje incompleto", "hours": hours}
                else:
                    cell = {"iso": fecha, "day": day.day, "status": "present", "label": "OK", "title": "Presente", "hours": hours}
            elif en_vacaciones:
                vacaciones_count += 1
                total_vacaciones += 1
                aus_just += 1
                total_justificadas += 1
                analisis_sector[sector]["justificadas"] += 1
                cell = {"iso": fecha, "day": day.day, "status": "vacation", "label": "V", "title": "Vacaciones", "hours": None}
            elif justificada:
                aus_just += 1
                total_justificadas += 1
                analisis_sector[sector]["justificadas"] += 1
                cell = {"iso": fecha, "day": day.day, "status": "justified", "label": "FJ", "title": "Falta justificada", "hours": None}
            else:
                aus_comp += 1
                total_ausencias += 1
                analisis_sector[sector]["ausencias"] += 1
                ausencias_rows.append({
                    "fecha": fecha,
                    "empleado": nombre,
                    "sector": sector,
                    "motivo": "Sin marca registrada",
                    "estado": "Computable",
                })
                cell = {"iso": fecha, "day": day.day, "status": "unjustified", "label": "X", "title": "Falta injustificada", "hours": None}
            cells.append(cell)

        total_presentes += presentes
        resumen_rows.append({
            "empleado": nombre,
            "sector": sector,
            "dias_laborables": posible,
            "presentes": presentes,
            "ausencias_computables": aus_comp,
            "ausencias_justificadas": aus_just,
            "ausentismo_pct": round((aus_comp * 100.0) / posible, 2) if posible else 0.0,
        })
        planilla_rows.append({
            "empleado_id": empleado_id,
            "empleado": nombre,
            "sector": sector,
            "cells": cells,
            "presentes": presentes,
            "vacaciones": vacaciones_count,
            "faltas_justificadas": aus_just,
            "faltas_injustificadas": aus_comp,
            "fichajes_incompletos": incompletos_count,
            "horas_trabajadas": round(horas_count, 2),
        })

    dias_posibles = sum(row["dias_laborables"] for row in resumen_rows)
    ausentismo_pct = round((total_ausencias * 100.0) / dias_posibles, 2) if dias_posibles else 0.0

    resumen_rows.sort(key=lambda r: r["empleado"])
    planilla_rows.sort(key=lambda r: r["empleado"])
    ausencias_rows.sort(key=lambda r: (r["fecha"], r["empleado"]))
    jornada_rows.sort(key=lambda r: (r["fecha"], r["empleado"]))
    analisis_rows = []
    for row in analisis_sector.values():
        posibles = row["posibles"]
        analisis_rows.append({
            **row,
            "posibles": posibles,
            "ausentismo_pct": round((row["ausencias"] * 100.0) / posibles, 2) if posibles else 0.0,
        })
    analisis_rows.sort(key=lambda r: (-r["ausencias"], r["sector"] or ""))

    return {
        "month_dates": month_dates,
        "laborable_dates": laborable_dates,
        "non_laborable_days": non_laborable_days,
        "kpis": {
            "ausentismo_pct": ausentismo_pct,
            "ausencias_computables": total_ausencias,
            "ausencias_justificadas": total_justificadas,
            "dias_laborables": len(laborable_dates),
            "empleados_activos": len(empleados_activos),
            "dias_posibles": dias_posibles,
            "presentes": total_presentes,
            "vacaciones": total_vacaciones,
            "fichajes_incompletos": total_fichajes_incompletos,
            "horas_trabajadas": round(total_horas_trabajadas, 2),
            "jornadas_mayores_12": jornadas_mayores_12,
            "sin_egreso": sin_egreso,
            "registros_mes": registros_mes,
        },
        "resumen_rows": resumen_rows,
        "ausencias_rows": ausencias_rows,
        "analisis_rows": analisis_rows,
        "jornada_rows": jornada_rows,
        "planilla_rows": planilla_rows,
    }

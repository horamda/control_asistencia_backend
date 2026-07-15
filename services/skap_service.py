from __future__ import annotations

import datetime as _dt
from collections import defaultdict

from extensions import get_db
from repositories.auditoria_repository import create as create_audit
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.puesto_repository import get_by_id as get_puesto_by_id
from repositories.roles_repository import get_roles_by_empleado
from repositories.skap_pregunta_repository import get_all_active_for_sector
from repositories.skap_pregunta_repository import get_by_id as get_pregunta_by_id
from repositories.skap_pregunta_repository import get_by_unique as get_pregunta_by_unique
from repositories.skap_pregunta_repository import get_page as get_preguntas_page
from repositories.skap_pregunta_repository import create as create_pregunta_row
from repositories.skap_pregunta_repository import count_all as count_preguntas
from repositories.skap_pregunta_repository import set_activo as set_pregunta_activo
from repositories.skap_pregunta_repository import update as update_pregunta_row
from repositories.skap_repository import (
    add_plan_action,
    create_evaluacion_detalles,
    create_plan,
    delete_plan_action,
    get_category_averages_rows,
    get_dashboard_summary,
    get_employee_ranking_rows,
    get_evaluacion_by_empleado_anio,
    get_evaluacion_by_id,
    get_evaluacion_detalles,
    get_evaluaciones_page,
    get_historical_evolution_rows,
    get_historial_empleado,
    get_plan_action_by_id,
    get_plan_actions,
    get_plan_by_empleado_anio,
    get_plan_by_evaluacion_id,
    get_pendientes_evaluacion as get_pendientes_evaluacion_rows,
    get_plan_by_id,
    get_planes_page,
    get_question_averages_rows,
    get_sector_ranking_rows,
    mark_pdp_generado,
    set_plan_action_estado,
    update_evaluacion_calculos,
    update_plan,
    update_plan_action,
)


CATEGORY_LABELS = {
    "S": "Skills",
    "K": "Knowledge",
    "A": "Attitude",
    "P": "Performance",
}

CATEGORY_ORDER = ["S", "K", "A", "P"]

ALLOWED_EVALUATOR_ROLES = {"supervisor", "jefe", "gerente", "manager", "admin", "rrhh"}

ACTION_STATUSES = {"pendiente", "en_proceso", "completado", "cancelado"}

LEVELS = [
    (4.50, 5.00, "Excelente"),
    (4.00, 4.49, "Destacado"),
    (3.00, 3.99, "Cumple"),
    (2.00, 2.99, "Necesita Desarrollo"),
    (0.00, 1.99, "Critico"),
]

BADGES = [
    (4.50, 5.00, "Oro"),
    (4.00, 4.49, "Plata"),
    (3.00, 3.99, "Bronce"),
]


def _fmt_dt(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ", timespec="minutes")
        except TypeError:
            return value.isoformat()
    return str(value)


def _fmt_date(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _fmt_time(value):
    if not value:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    return str(value)


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _categoria_label(categoria: str | None) -> str:
    return CATEGORY_LABELS.get(str(categoria or "").strip().upper(), str(categoria or "").strip() or "-")


def _nivel_from_avg(avg: float) -> str:
    avg = float(avg or 0)
    for low, high, label in LEVELS:
        if low <= avg <= high:
            return label
    return "Critico"


def _badge_from_avg(avg: float) -> str | None:
    avg = float(avg or 0)
    for low, high, label in BADGES:
        if low <= avg <= high:
            return label
    return None


def _weighted_average(rows: list[dict], score_key: str, weight_key: str) -> float:
    total_weight = 0.0
    total_score = 0.0
    for row in rows:
        weight = _to_float(row.get(weight_key), 1.0)
        if weight <= 0:
            weight = 1.0
        score = _to_float(row.get(score_key), 0.0)
        total_weight += weight
        total_score += score * weight
    if total_weight <= 0:
        return 0.0
    return round(total_score / total_weight, 2)


def _current_dt():
    return _dt.datetime.now()


def _current_date():
    return _dt.date.today()


def _current_year():
    return _current_date().year


def _employee_full_name(empleado: dict | None) -> str | None:
    if not empleado:
        return None
    parts = [
        str(empleado.get("apellido") or "").strip(),
        str(empleado.get("nombre") or "").strip(),
    ]
    name = " ".join(part for part in parts if part)
    return name or None


def _require_empleado(empleado_id: int) -> dict:
    empleado = get_empleado_by_id(int(empleado_id))
    if not empleado or not empleado.get("activo"):
        raise ValueError("Empleado no encontrado o inactivo.")
    return empleado


def _get_roles(empleado_id: int) -> set[str]:
    return {
        str(row.get("nombre") or "").strip().lower()
        for row in get_roles_by_empleado(int(empleado_id))
        if str(row.get("nombre") or "").strip()
    }


def _can_evaluate(evaluator: dict, target_empleado: dict) -> bool:
    roles = _get_roles(int(evaluator["id"]))
    if roles & ALLOWED_EVALUATOR_ROLES:
        return True
    boss_id = int(target_empleado.get("reporta_a_empleado_id") or 0)
    return boss_id > 0 and boss_id == int(evaluator["id"])


def _normalize_categoria(value: str | None) -> str:
    categoria = str(value or "").strip().upper()
    if categoria not in CATEGORY_LABELS:
        raise ValueError("Categoria invalida.")
    return categoria


def _normalize_estado(value: str | None) -> str:
    estado = str(value or "").strip().lower()
    if estado not in ACTION_STATUSES:
        raise ValueError("Estado invalido.")
    return estado


def serialize_pregunta(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "sector_id": row.get("sector_id"),
        "sector_nombre": row.get("sector_nombre"),
        "puesto_id": row.get("puesto_id"),
        "puesto_nombre": row.get("puesto_nombre"),
        "categoria": row.get("categoria"),
        "categoria_label": _categoria_label(row.get("categoria")),
        "descripcion": row.get("descripcion"),
        "peso": _to_float(row.get("peso"), 1.0),
        "puntaje_esperado": _to_int(row.get("puntaje_esperado"), 4),
        "requiere_observacion": bool(row.get("requiere_observacion")),
        "requiere_evidencia": bool(row.get("requiere_evidencia")),
        "activo": bool(row.get("activo")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
    }


def serialize_evaluacion_detalle(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row.get("id"),
        "evaluacion_id": row.get("evaluacion_id"),
        "pregunta_id": row.get("pregunta_id"),
        "categoria": row.get("categoria"),
        "categoria_label": _categoria_label(row.get("categoria")),
        "descripcion": row.get("descripcion_snapshot"),
        "peso": _to_float(row.get("peso_snapshot"), 1.0),
        "puntaje_esperado": _to_int(row.get("puntaje_esperado_snapshot"), 4),
        "puntaje_obtenido": _to_int(row.get("puntaje_obtenido"), 0),
        "observacion": row.get("observacion"),
        "evidencia": row.get("evidencia"),
        "cumple_esperado": bool(row.get("cumple_esperado")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
    }


def serialize_plan_action(row: dict) -> dict:
    if not row:
        return {}
    estado_actual = str(row.get("estado_actual") or row.get("estado") or "pendiente").strip().lower()
    return {
        "id": row.get("id"),
        "plan_id": row.get("plan_id"),
        "categoria": row.get("categoria"),
        "categoria_label": _categoria_label(row.get("categoria")),
        "accion": row.get("accion"),
        "responsable_empleado_id": row.get("responsable_empleado_id"),
        "responsable": {
            "id": row.get("responsable_empleado_id"),
            "nombre": row.get("responsable_nombre"),
            "legajo": row.get("responsable_legajo"),
        } if row.get("responsable_empleado_id") else None,
        "fecha_compromiso": _fmt_date(row.get("fecha_compromiso")),
        "estado": row.get("estado"),
        "estado_actual": estado_actual,
        "es_vencido": estado_actual == "vencido",
        "completado_at": _fmt_dt(row.get("completado_at")),
        "comentarios": row.get("comentarios"),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
    }


def serialize_plan(row: dict, acciones: list[dict] | None = None) -> dict:
    if not row:
        return {}
    acciones = acciones or []
    acciones_total = _to_int(row.get("acciones_total"), len(acciones))
    acciones_completadas = _to_int(row.get("acciones_completadas"))
    acciones_vencidas = _to_int(row.get("acciones_vencidas"))
    avance_pct = round((acciones_completadas * 100.0) / acciones_total, 1) if acciones_total else 0.0
    return {
        "id": row.get("id"),
        "evaluacion_id": row.get("evaluacion_id"),
        "empresa_id": row.get("empresa_id"),
        "empleado_id": row.get("empleado_id"),
        "sector_id": row.get("sector_id"),
        "puesto_id": row.get("puesto_id"),
        "anio": row.get("anio"),
        "promedio_general": _to_float(row.get("promedio_general"), 0.0),
        "nivel": row.get("nivel"),
        "observaciones": row.get("observaciones"),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
        "evaluacion": {
            "fecha_evaluacion": _fmt_date(row.get("fecha_evaluacion")),
            "hora_evaluacion": _fmt_time(row.get("hora_evaluacion")),
            "promedio_skills": _to_float(row.get("promedio_skills"), 0.0),
            "promedio_knowledge": _to_float(row.get("promedio_knowledge"), 0.0),
            "promedio_attitude": _to_float(row.get("promedio_attitude"), 0.0),
            "promedio_performance": _to_float(row.get("promedio_performance"), 0.0),
        },
        "empleado": {
            "id": row.get("empleado_id"),
            "legajo": row.get("empleado_legajo"),
            "dni": row.get("empleado_dni"),
            "nombre": _employee_full_name({
                "apellido": row.get("empleado_apellido"),
                "nombre": row.get("empleado_nombre"),
            }),
        },
        "sector": {
            "id": row.get("sector_id"),
            "nombre": row.get("sector_nombre"),
        },
        "puesto": {
            "id": row.get("puesto_id"),
            "nombre": row.get("puesto_nombre"),
        } if row.get("puesto_id") else None,
        "evaluador": {
            "id": row.get("evaluador_empleado_id"),
            "nombre": _employee_full_name({
                "apellido": row.get("evaluador_apellido"),
                "nombre": row.get("evaluador_nombre"),
            }),
        },
        "acciones_total": acciones_total,
        "acciones_completadas": acciones_completadas,
        "acciones_vencidas": acciones_vencidas,
        "avance_pct": avance_pct,
        "acciones": [serialize_plan_action(a) for a in acciones],
    }


def _category_aggregates(detalles: list[dict]) -> dict[str, dict]:
    aggs: dict[str, dict] = {
        categoria: {
            "categoria": categoria,
            "label": CATEGORY_LABELS[categoria],
            "items": [],
            "peso_total": 0.0,
            "score_total": 0.0,
            "expected_total": 0.0,
        }
        for categoria in CATEGORY_ORDER
    }
    for detalle in detalles:
        categoria = str(detalle.get("categoria") or "").strip().upper()
        if categoria not in aggs:
            continue
        weight = _to_float(detalle.get("peso_snapshot"), 1.0)
        if weight <= 0:
            weight = 1.0
        score = _to_float(detalle.get("puntaje_obtenido"), 0.0)
        expected = _to_float(detalle.get("puntaje_esperado_snapshot"), 4.0)
        aggs[categoria]["items"].append(detalle)
        aggs[categoria]["peso_total"] += weight
        aggs[categoria]["score_total"] += score * weight
        aggs[categoria]["expected_total"] += expected * weight
    for categoria in CATEGORY_ORDER:
        agg = aggs[categoria]
        peso = agg["peso_total"]
        agg["promedio"] = round(agg["score_total"] / peso, 2) if peso else 0.0
        agg["esperado"] = round(agg["expected_total"] / peso, 2) if peso else 0.0
        agg["nivel"] = _nivel_from_avg(agg["promedio"])
    return aggs


def _build_category_cards(detalles: list[dict]) -> list[dict]:
    aggs = _category_aggregates(detalles)
    cards = []
    for categoria in CATEGORY_ORDER:
        agg = aggs[categoria]
        cards.append(
            {
                "categoria": categoria,
                "label": agg["label"],
                "promedio": agg["promedio"],
                "esperado": agg["esperado"],
                "nivel": agg["nivel"],
                "respuestas": len(agg["items"]),
                "badge": _badge_from_avg(agg["promedio"]),
            }
        )
    return cards


def _build_gap_actions(
    *,
    detalles: list[dict],
    evaluator_empleado_id: int,
    fecha_base: _dt.date,
) -> tuple[list[dict], str]:
    aggs = _category_aggregates(detalles)
    gaps = []
    for categoria in CATEGORY_ORDER:
        agg = aggs[categoria]
        if not agg["items"]:
            continue
        if agg["promedio"] >= max(agg["esperado"], 3.0):
            continue
        weak_items = sorted(
            agg["items"],
            key=lambda r: (
                _to_float(r.get("puntaje_obtenido"), 0.0) - _to_float(r.get("puntaje_esperado_snapshot"), 4.0),
                _to_float(r.get("peso_snapshot"), 1.0),
                str(r.get("descripcion_snapshot") or ""),
            ),
        )
        sample = [str(item.get("descripcion_snapshot") or "").strip() for item in weak_items[:2] if str(item.get("descripcion_snapshot") or "").strip()]
        if sample:
            detalle_text = "; ".join(sample)
        else:
            detalle_text = f"Reforzar {agg['label']}."
        gaps.append(
            {
                "categoria": categoria,
                "accion": f"Fortalecer {agg['label']}: {detalle_text}",
                "responsable_empleado_id": evaluator_empleado_id,
                "fecha_compromiso": (fecha_base + _dt.timedelta(days=90)).isoformat(),
                "estado": "pendiente",
                "comentarios": (
                    f"Promedio {agg['promedio']:.2f} vs esperado {agg['esperado']:.2f}. "
                    f"Preguntas con brecha: {detalle_text}"
                ),
            }
        )
    if not gaps:
        return [], "Sin brechas relevantes detectadas. Mantener seguimiento de fortalezas."
    resumen = ", ".join(f"{gap['categoria']} ({_categoria_label(gap['categoria'])})" for gap in gaps)
    return gaps, f"Brechas detectadas en: {resumen}."


def _build_plan_row_from_evaluacion(evaluacion: dict, detalles: list[dict]) -> tuple[dict, list[dict]]:
    acciones, observaciones = _build_gap_actions(
        detalles=detalles,
        evaluator_empleado_id=int(evaluacion["evaluador_empleado_id"]),
        fecha_base=_dt.date.fromisoformat(str(evaluacion["fecha_evaluacion"])),
    )
    plan_row = {
        "evaluacion_id": evaluacion["id"],
        "empresa_id": evaluacion["empresa_id"],
        "empleado_id": evaluacion["empleado_id"],
        "sector_id": evaluacion["sector_id"],
        "puesto_id": evaluacion.get("puesto_id"),
        "anio": evaluacion["anio"],
        "promedio_general": _to_float(evaluacion.get("promedio_general"), 0.0),
        "nivel": evaluacion.get("nivel"),
        "observaciones": observaciones,
    }
    return plan_row, acciones


def _insert_plan_and_actions(cursor, plan_row: dict, actions: list[dict]) -> int:
    cursor.execute(
        """
        INSERT INTO skap_planes_desarrollo
        (
            evaluacion_id,
            empresa_id,
            empleado_id,
            sector_id,
            puesto_id,
            anio,
            promedio_general,
            nivel,
            observaciones
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            plan_row.get("evaluacion_id"),
            plan_row.get("empresa_id"),
            plan_row.get("empleado_id"),
            plan_row.get("sector_id"),
            plan_row.get("puesto_id"),
            plan_row.get("anio"),
            plan_row.get("promedio_general"),
            plan_row.get("nivel"),
            plan_row.get("observaciones"),
        ),
    )
    plan_id = cursor.lastrowid
    for action in actions:
        cursor.execute(
            """
            INSERT INTO skap_planes_desarrollo_acciones
            (
                plan_id,
                categoria,
                accion,
                responsable_empleado_id,
                fecha_compromiso,
                estado,
                comentarios,
                completado_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                plan_id,
                action.get("categoria"),
                action.get("accion"),
                action.get("responsable_empleado_id"),
                action.get("fecha_compromiso"),
                action.get("estado") or "pendiente",
                action.get("comentarios"),
                action.get("completado_at"),
            ),
        )
    return plan_id


def _serialize_evaluacion_full(row: dict | None, *, detalles: list[dict] | None = None, plan: dict | None = None) -> dict:
    if not row:
        return {}
    detalles = detalles or []
    category_cards = _build_category_cards(detalles) if detalles else [
        {
            "categoria": categoria,
            "label": CATEGORY_LABELS[categoria],
            "promedio": _to_float(row.get(f"promedio_{'knowledge' if categoria == 'K' else 'performance' if categoria == 'P' else 'attitude' if categoria == 'A' else 'skills'}"), 0.0),
            "esperado": 0.0,
            "nivel": _nivel_from_avg(_to_float(row.get("promedio_general"), 0.0)),
            "respuestas": 0,
            "badge": _badge_from_avg(_to_float(row.get("promedio_general"), 0.0)),
        }
        for categoria in CATEGORY_ORDER
    ]
    badge = _badge_from_avg(_to_float(row.get("promedio_general"), 0.0))
    return {
        "id": row.get("id"),
        "empresa_id": row.get("empresa_id"),
        "anio": row.get("anio"),
        "fecha_evaluacion": _fmt_date(row.get("fecha_evaluacion")),
        "hora_evaluacion": _fmt_time(row.get("hora_evaluacion")),
        "empleado": {
            "id": row.get("empleado_id"),
            "legajo": row.get("empleado_legajo"),
            "dni": row.get("empleado_dni"),
            "nombre": _employee_full_name({
                "apellido": row.get("empleado_apellido"),
                "nombre": row.get("empleado_nombre"),
            }),
        },
        "sector": {
            "id": row.get("sector_id"),
            "nombre": row.get("sector_nombre"),
        },
        "puesto": {
            "id": row.get("puesto_id"),
            "nombre": row.get("puesto_nombre"),
        } if row.get("puesto_id") else None,
        "evaluador": {
            "id": row.get("evaluador_empleado_id"),
            "legajo": row.get("evaluador_legajo"),
            "nombre": _employee_full_name({
                "apellido": row.get("evaluador_apellido"),
                "nombre": row.get("evaluador_nombre"),
            }),
            "usuario": row.get("evaluador_usuario"),
        },
        "promedios": {
            "skills": _to_float(row.get("promedio_skills"), 0.0),
            "knowledge": _to_float(row.get("promedio_knowledge"), 0.0),
            "attitude": _to_float(row.get("promedio_attitude"), 0.0),
            "performance": _to_float(row.get("promedio_performance"), 0.0),
            "general": _to_float(row.get("promedio_general"), 0.0),
        },
        "nivel": row.get("nivel"),
        "badge": badge,
        "observaciones_generales": row.get("observaciones_generales"),
        "pdp_generado_at": _fmt_dt(row.get("pdp_generado_at")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
        "categoria_cards": category_cards,
        "detalles": [serialize_evaluacion_detalle(detalle) for detalle in detalles],
        "plan": serialize_plan(plan, get_plan_actions(plan["id"])) if plan else None,
    }


def serialize_evaluacion(row: dict | None, *, detalles: list[dict] | None = None, plan: dict | None = None) -> dict:
    return _serialize_evaluacion_full(row, detalles=detalles, plan=plan)


def can_evaluate_employee(evaluator_empleado_id: int, target_empleado_id: int | None = None) -> bool:
    evaluator = _require_empleado(int(evaluator_empleado_id))
    roles = _get_roles(int(evaluator_empleado_id))
    if roles & ALLOWED_EVALUATOR_ROLES:
        return True
    if target_empleado_id is None:
        return False
    target = _require_empleado(int(target_empleado_id))
    return _can_evaluate(evaluator, target)


def create_evaluacion(
    *,
    empleado_id: int,
    evaluador_empleado_id: int,
    evaluador_usuario_id: int | None = None,
    anio: int | None = None,
    respuestas: list[dict] | None = None,
    observaciones_generales: str | None = None,
) -> dict:
    respuestas = list(respuestas or [])
    if not respuestas:
        raise ValueError("Debes enviar respuestas para la evaluacion.")

    empleado = _require_empleado(int(empleado_id))
    evaluador = _require_empleado(int(evaluador_empleado_id))
    if not _can_evaluate(evaluador, empleado):
        raise ValueError("No tiene permisos para evaluar a este empleado.")

    sector_id = int(empleado.get("sector_id") or 0)
    puesto_id = int(empleado.get("puesto_id") or 0) or None
    if not sector_id:
        raise ValueError("El empleado no tiene sector asignado.")

    questions = get_all_active_for_sector(sector_id, puesto_id=puesto_id)
    if not questions:
        raise ValueError("No hay preguntas activas para el sector/puesto del empleado.")

    question_by_id = {int(row["id"]): row for row in questions}
    response_by_id: dict[int, dict] = {}
    for item in respuestas:
        pregunta_id = _to_int(item.get("pregunta_id"))
        if not pregunta_id:
            raise ValueError("Cada respuesta debe incluir pregunta_id.")
        if pregunta_id in response_by_id:
            raise ValueError("No puede repetir preguntas en la evaluacion.")
        response_by_id[pregunta_id] = item

    missing = [qid for qid in question_by_id if qid not in response_by_id]
    extra = [qid for qid in response_by_id if qid not in question_by_id]
    if missing:
        raise ValueError("Faltan respuestas para preguntas activas del sector/puesto.")
    if extra:
        raise ValueError("Se enviaron preguntas que no pertenecen al sector/puesto del empleado.")

    detalles = []
    for pregunta in questions:
        resp = response_by_id[int(pregunta["id"])]
        puntaje = _to_int(resp.get("puntaje") if resp.get("puntaje") is not None else resp.get("score"))
        if puntaje < 1 or puntaje > 5:
            raise ValueError("Cada puntaje debe estar entre 1 y 5.")
        observacion = str(resp.get("observacion") or resp.get("observation") or "").strip() or None
        evidencia = str(resp.get("evidencia") or resp.get("evidence") or "").strip() or None
        if pregunta.get("requiere_observacion") and not observacion:
            raise ValueError(f"La pregunta '{pregunta.get('descripcion')}' requiere observacion.")
        if pregunta.get("requiere_evidencia") and not evidencia:
            raise ValueError(f"La pregunta '{pregunta.get('descripcion')}' requiere evidencia.")
        detalle = {
            "pregunta_id": int(pregunta["id"]),
            "categoria": str(pregunta["categoria"]).strip().upper(),
            "descripcion_snapshot": pregunta["descripcion"],
            "peso_snapshot": _to_float(pregunta.get("peso"), 1.0),
            "puntaje_esperado_snapshot": _to_int(pregunta.get("puntaje_esperado"), 4),
            "puntaje_obtenido": puntaje,
            "observacion": observacion,
            "evidencia": evidencia,
            "cumple_esperado": puntaje >= _to_int(pregunta.get("puntaje_esperado"), 4),
        }
        detalles.append(detalle)

    category_aggs = _category_aggregates(detalles)
    promedio_skills = category_aggs["S"]["promedio"]
    promedio_knowledge = category_aggs["K"]["promedio"]
    promedio_attitude = category_aggs["A"]["promedio"]
    promedio_performance = category_aggs["P"]["promedio"]
    promedio_general = _weighted_average(detalles, "puntaje_obtenido", "peso_snapshot")
    nivel = _nivel_from_avg(promedio_general)

    anio = int(anio or _current_year())
    fecha_now = _current_dt()
    fecha_evaluacion = fecha_now.date()
    hora_evaluacion = fecha_now.time().replace(microsecond=0)
    observaciones_generales = str(observaciones_generales or "").strip() or None

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT 1
            FROM skap_evaluaciones
            WHERE empleado_id = %s
              AND anio = %s
            LIMIT 1
            """,
            (int(empleado["id"]), anio),
        )
        if cursor.fetchone():
            raise ValueError("El empleado ya tiene una evaluacion para ese anio.")

        cursor.execute(
            """
            INSERT INTO skap_evaluaciones
            (
                empresa_id,
                empleado_id,
                sector_id,
                puesto_id,
                anio,
                evaluador_empleado_id,
                evaluador_usuario_id,
                fecha_evaluacion,
                hora_evaluacion,
                promedio_skills,
                promedio_knowledge,
                promedio_attitude,
                promedio_performance,
                promedio_general,
                nivel,
                observaciones_generales
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                empleado.get("empresa_id"),
                int(empleado["id"]),
                sector_id,
                puesto_id,
                anio,
                int(evaluador["id"]),
                evaluador_usuario_id,
                fecha_evaluacion,
                hora_evaluacion,
                promedio_skills,
                promedio_knowledge,
                promedio_attitude,
                promedio_performance,
                promedio_general,
                nivel,
                observaciones_generales,
            ),
        )
        evaluacion_id = cursor.lastrowid

        for detalle in detalles:
            cursor.execute(
                """
                INSERT INTO skap_evaluaciones_detalle
                (
                    evaluacion_id,
                    pregunta_id,
                    categoria,
                    descripcion_snapshot,
                    peso_snapshot,
                    puntaje_esperado_snapshot,
                    puntaje_obtenido,
                    observacion,
                    evidencia,
                    cumple_esperado
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    evaluacion_id,
                    detalle["pregunta_id"],
                    detalle["categoria"],
                    detalle["descripcion_snapshot"],
                    detalle["peso_snapshot"],
                    detalle["puntaje_esperado_snapshot"],
                    detalle["puntaje_obtenido"],
                    detalle["observacion"],
                    detalle["evidencia"],
                    1 if detalle["cumple_esperado"] else 0,
                ),
            )

        plan_row, actions = _build_plan_row_from_evaluacion(
            {
                "id": evaluacion_id,
                "empresa_id": empleado.get("empresa_id"),
                "empleado_id": empleado.get("id"),
                "sector_id": sector_id,
                "puesto_id": puesto_id,
                "anio": anio,
                "promedio_general": promedio_general,
                "nivel": nivel,
                "evaluador_empleado_id": evaluador.get("id"),
                "fecha_evaluacion": fecha_evaluacion,
            },
            detalles,
        )
        plan_id = _insert_plan_and_actions(cursor, plan_row, actions)
        cursor.execute(
            """
            UPDATE skap_evaluaciones
            SET pdp_generado_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (evaluacion_id,),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()

    evaluacion = get_evaluacion_by_id(evaluacion_id)
    detalle_rows = get_evaluacion_detalles(evaluacion_id)
    plan = get_plan_by_id(plan_id)
    acciones = get_plan_actions(plan_id)
    plan_serializado = serialize_plan(plan, acciones) if plan else None
    create_audit(None, "create", "skap_evaluaciones", evaluacion_id)
    create_audit(None, "create", "skap_planes_desarrollo", plan_id)
    return {
        "evaluacion": _serialize_evaluacion_full(evaluacion, detalles=detalle_rows, plan=plan),
        "plan": plan_serializado,
    }


def ensure_plan_for_evaluacion(
    evaluacion_id: int,
    *,
    acciones_extra: list[dict] | None = None,
) -> dict:
    evaluacion = get_evaluacion_by_id(int(evaluacion_id))
    if not evaluacion:
        raise ValueError("Evaluacion no encontrada.")
    detalles = get_evaluacion_detalles(int(evaluacion_id))
    plan = get_plan_by_evaluacion_id(int(evaluacion_id))
    if plan:
        if acciones_extra:
            for action in acciones_extra:
                add_plan_action(
                    {
                        "plan_id": plan["id"],
                        "categoria": action.get("categoria"),
                        "accion": action.get("accion"),
                        "responsable_empleado_id": action.get("responsable_empleado_id") or evaluacion.get("evaluador_empleado_id"),
                        "fecha_compromiso": action.get("fecha_compromiso"),
                        "estado": action.get("estado") or "pendiente",
                        "comentarios": action.get("comentarios"),
                        "completado_at": action.get("completado_at"),
                    }
                )
            plan = get_plan_by_id(int(plan["id"]))
        acciones = get_plan_actions(int(plan["id"]))
        return serialize_plan(plan, acciones)

    plan_row, actions = _build_plan_row_from_evaluacion(evaluacion, detalles)
    if acciones_extra:
        for action in acciones_extra:
            actions.append(
                {
                    "categoria": action.get("categoria"),
                    "accion": action.get("accion"),
                    "responsable_empleado_id": action.get("responsable_empleado_id") or evaluacion.get("evaluador_empleado_id"),
                    "fecha_compromiso": action.get("fecha_compromiso"),
                    "estado": action.get("estado") or "pendiente",
                    "comentarios": action.get("comentarios"),
                    "completado_at": action.get("completado_at"),
                }
            )

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        plan_id = _insert_plan_and_actions(cursor, plan_row, actions)
        cursor.execute(
            """
            UPDATE skap_evaluaciones
            SET pdp_generado_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(evaluacion_id),),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()

    create_audit(None, "create", "skap_planes_desarrollo", plan_id)
    plan = get_plan_by_id(plan_id)
    acciones = get_plan_actions(plan_id)
    return serialize_plan(plan, acciones)


def get_mi_desarrollo(
    *,
    empleado_id: int,
    anio: int | None = None,
) -> dict:
    empleado = _require_empleado(int(empleado_id))
    historial = get_historial_empleado(int(empleado["id"]), empresa_id=empleado.get("empresa_id"))
    selected_year = int(anio or (historial[0]["anio"] if historial else _current_year()))
    evaluacion = get_evaluacion_by_empleado_anio(int(empleado["id"]), selected_year)
    if not evaluacion and not anio and historial:
        selected_year = int(historial[0]["anio"])
        evaluacion = get_evaluacion_by_empleado_anio(int(empleado["id"]), selected_year)

    detalles = get_evaluacion_detalles(int(evaluacion["id"])) if evaluacion else []
    plan = get_plan_by_empleado_anio(int(empleado["id"]), selected_year, empresa_id=empleado.get("empresa_id")) if evaluacion else None
    acciones = get_plan_actions(int(plan["id"])) if plan else []

    ranking_rows = get_employee_ranking_rows(
        anio=selected_year,
        empresa_id=empleado.get("empresa_id"),
        sector_id=empleado.get("sector_id") or None,
    )
    posicion = None
    total_ranking = len(ranking_rows)
    ranking_score = None
    ranking_sector_nombre = None
    for index, row in enumerate(ranking_rows, start=1):
        if int(row.get("empleado_id") or 0) == int(empleado["id"]):
            posicion = index
            ranking_score = _to_float(row.get("promedio_general"), 0.0)
            ranking_sector_nombre = row.get("sector_nombre")
            break

    payload = {
        "empleado": {
            "id": empleado.get("id"),
            "legajo": empleado.get("legajo"),
            "dni": empleado.get("dni"),
            "nombre": _employee_full_name(empleado),
            "sector_id": empleado.get("sector_id"),
            "puesto_id": empleado.get("puesto_id"),
            "empresa_id": empleado.get("empresa_id"),
        },
        "anio_evaluado": selected_year,
        "evaluacion": _serialize_evaluacion_full(evaluacion, detalles=detalles, plan=plan) if evaluacion else None,
        "categoria_cards": _build_category_cards(detalles) if detalles else [],
        "historial": [
            {
                "anio": int(row.get("anio") or 0),
                "promedio_general": _to_float(row.get("promedio_general"), 0.0),
                "nivel": row.get("nivel"),
                "sector_nombre": row.get("sector_nombre"),
            }
            for row in sorted(historial, key=lambda r: int(r.get("anio") or 0))
        ],
        "plan": serialize_plan(plan, acciones) if plan else None,
        "ranking": {
            "posicion": posicion,
            "total": total_ranking,
            "sector_nombre": ranking_sector_nombre or (empleado.get("sector_nombre") if empleado.get("sector_nombre") else None),
            "puntaje": ranking_score,
        },
        "badge": _badge_from_avg(_to_float(evaluacion.get("promedio_general"), 0.0) if evaluacion else 0.0),
    }
    return payload


def get_personal_ranking(
    *,
    empleado_id: int,
    anio: int | None = None,
) -> dict:
    empleado = _require_empleado(int(empleado_id))
    selected_year = int(anio or _current_year())
    ranking_rows = get_employee_ranking_rows(
        anio=selected_year,
        empresa_id=empleado.get("empresa_id"),
        sector_id=empleado.get("sector_id") or None,
    )
    posicion = None
    total = len(ranking_rows)
    score = None
    nivel = None
    for index, row in enumerate(ranking_rows, start=1):
        if int(row.get("empleado_id") or 0) == int(empleado["id"]):
            posicion = index
            score = _to_float(row.get("promedio_general"), 0.0)
            nivel = row.get("nivel")
            break
    return {
        "anio": selected_year,
        "posicion": posicion,
        "total": total,
        "puntaje": score,
        "nivel": nivel,
        "badge": _badge_from_avg(score or 0.0),
    }


def get_dashboard_data(
    *,
    anio: int | None = None,
    empresa_id: int | None = None,
    sector_id: int | None = None,
) -> dict:
    anio = int(anio or _current_year())
    resumen = get_dashboard_summary(anio=anio, empresa_id=empresa_id, sector_id=sector_id)
    sector_ranking = get_sector_ranking_rows(anio=anio, empresa_id=empresa_id, sector_id=sector_id)
    ranking_rows = get_employee_ranking_rows(anio=anio, empresa_id=empresa_id, sector_id=sector_id)
    historial = get_historical_evolution_rows(empresa_id=empresa_id, sector_id=sector_id)
    categorias = get_category_averages_rows(anio=anio, empresa_id=empresa_id, sector_id=sector_id)
    preguntas_debiles = get_question_averages_rows(anio=anio, empresa_id=empresa_id, sector_id=sector_id, limit=5, ascending=True)
    preguntas_fuertes = get_question_averages_rows(anio=anio, empresa_id=empresa_id, sector_id=sector_id, limit=5, ascending=False)

    destacados = []
    criticos = []
    for row in ranking_rows[:5]:
        destacados.append(
            {
                "empleado_id": row.get("empleado_id"),
                "legajo": row.get("legajo"),
                "apellido": row.get("apellido"),
                "nombre": row.get("nombre"),
                "sector_nombre": row.get("sector_nombre"),
                "puesto_nombre": row.get("puesto_nombre"),
                "promedio_general": _to_float(row.get("promedio_general"), 0.0),
                "nivel": row.get("nivel"),
            }
        )
    for row in sorted(ranking_rows, key=lambda r: (_to_float(r.get("promedio_general"), 0.0), str(r.get("apellido") or ""), str(r.get("nombre") or "")))[:5]:
        criticos.append(
            {
                "empleado_id": row.get("empleado_id"),
                "legajo": row.get("legajo"),
                "apellido": row.get("apellido"),
                "nombre": row.get("nombre"),
                "sector_nombre": row.get("sector_nombre"),
                "puesto_nombre": row.get("puesto_nombre"),
                "promedio_general": _to_float(row.get("promedio_general"), 0.0),
                "nivel": row.get("nivel"),
            }
        )

    return {
        "anio": anio,
        "resumen": resumen,
        "sector_ranking": [
            {
                "sector_id": row.get("sector_id"),
                "sector_nombre": row.get("sector_nombre"),
                "evaluaciones": _to_int(row.get("evaluaciones"), 0),
                "promedio_general": _to_float(row.get("promedio_general"), 0.0),
                "promedio_skills": _to_float(row.get("promedio_skills"), 0.0),
                "promedio_knowledge": _to_float(row.get("promedio_knowledge"), 0.0),
                "promedio_attitude": _to_float(row.get("promedio_attitude"), 0.0),
                "promedio_performance": _to_float(row.get("promedio_performance"), 0.0),
            }
            for row in sector_ranking
        ],
        "historical_evolution": [
            {
                "anio": _to_int(row.get("anio"), 0),
                "evaluaciones": _to_int(row.get("evaluaciones"), 0),
                "promedio_general": _to_float(row.get("promedio_general"), 0.0),
            }
            for row in historial
        ],
        "category_averages": [
            {
                "categoria": row.get("categoria"),
                "label": _categoria_label(row.get("categoria")),
                "respuestas": _to_int(row.get("respuestas"), 0),
                "promedio_obtenido": _to_float(row.get("promedio_obtenido"), 0.0),
                "promedio_esperado": _to_float(row.get("promedio_esperado"), 0.0),
            }
            for row in categorias
        ],
        "weakest_competencies": [
            {
                "pregunta_id": row.get("pregunta_id"),
                "categoria": row.get("categoria"),
                "categoria_label": _categoria_label(row.get("categoria")),
                "descripcion": row.get("descripcion_snapshot"),
                "respuestas": _to_int(row.get("respuestas"), 0),
                "promedio_obtenido": _to_float(row.get("promedio_obtenido"), 0.0),
                "promedio_esperado": _to_float(row.get("promedio_esperado"), 0.0),
                "peso_promedio": _to_float(row.get("peso_promedio"), 0.0),
            }
            for row in preguntas_debiles
        ],
        "strongest_competencies": [
            {
                "pregunta_id": row.get("pregunta_id"),
                "categoria": row.get("categoria"),
                "categoria_label": _categoria_label(row.get("categoria")),
                "descripcion": row.get("descripcion_snapshot"),
                "respuestas": _to_int(row.get("respuestas"), 0),
                "promedio_obtenido": _to_float(row.get("promedio_obtenido"), 0.0),
                "promedio_esperado": _to_float(row.get("promedio_esperado"), 0.0),
                "peso_promedio": _to_float(row.get("peso_promedio"), 0.0),
            }
            for row in preguntas_fuertes
        ],
        "destacados": destacados,
        "criticos": criticos,
    }


def get_preguntas_catalogo(
    *,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    sector_id: int | None = None,
    puesto_filter: int | None = None,
    categoria: str | None = None,
    activo: int | None = None,
):
    rows, total = get_preguntas_page(
        page,
        per_page,
        search=search,
        sector_id=sector_id,
        puesto_filter=puesto_filter,
        categoria=categoria,
        activo=activo,
    )
    return [serialize_pregunta(row) for row in rows], total


def get_preguntas_por_sector(sector_id: int, *, puesto_id: int | None = None, categoria: str | None = None):
    rows = get_all_active_for_sector(int(sector_id), puesto_id=puesto_id, categoria=categoria)
    return [serialize_pregunta(row) for row in rows]


def get_pendientes_evaluacion(*, sector_id: int, anio: int, sucursal_id: int | None = None):
    rows = get_pendientes_evaluacion_rows(sector_id=int(sector_id), anio=int(anio), sucursal_id=sucursal_id)
    return [
        {
            "id": row.get("id"),
            "legajo": row.get("legajo"),
            "apellido": row.get("apellido"),
            "nombre": row.get("nombre"),
            "dni": row.get("dni"),
            "sucursal_id": row.get("sucursal_id"),
            "sucursal_nombre": row.get("sucursal_nombre"),
            "puesto_id": row.get("puesto_id"),
            "puesto_nombre": row.get("puesto_nombre"),
            "reporta_a_empleado_id": row.get("reporta_a_empleado_id"),
            "jefe_nombre": (
                f"{row.get('jefe_apellido')}, {row.get('jefe_nombre')}"
                if row.get("reporta_a_empleado_id")
                else None
            ),
        }
        for row in rows
    ]


def _normalize_puesto_id(data: dict) -> int | None:
    puesto_id = _to_int(data.get("puesto_id")) or None
    if puesto_id and not get_puesto_by_id(int(puesto_id)):
        raise ValueError("Puesto no encontrado.")
    return puesto_id


def crear_pregunta(data: dict) -> int:
    if not data.get("sector_id"):
        raise ValueError("Sector es obligatorio.")
    data["categoria"] = _normalize_categoria(data.get("categoria"))
    data["descripcion"] = str(data.get("descripcion") or "").strip()
    if not data["descripcion"]:
        raise ValueError("La descripcion es obligatoria.")
    data["peso"] = _to_float(data.get("peso"), 1.0)
    if data["peso"] <= 0:
        raise ValueError("El peso debe ser mayor a cero.")
    data["puntaje_esperado"] = _to_int(data.get("puntaje_esperado"), 4)
    if data["puntaje_esperado"] < 1 or data["puntaje_esperado"] > 5:
        raise ValueError("El puntaje esperado debe estar entre 1 y 5.")
    data["puesto_id"] = _normalize_puesto_id(data)
    if get_pregunta_by_unique(int(data["sector_id"]), data["categoria"], data["descripcion"], puesto_id=data["puesto_id"]):
        raise ValueError("Ya existe una pregunta igual para ese sector, puesto y categoria.")
    return create_pregunta_row(data)


def actualizar_pregunta(pregunta_id: int, data: dict) -> None:
    existing = get_pregunta_by_id(int(pregunta_id))
    if not existing:
        raise ValueError("Pregunta no encontrada.")
    if not data.get("sector_id"):
        raise ValueError("Sector es obligatorio.")
    data["categoria"] = _normalize_categoria(data.get("categoria"))
    data["descripcion"] = str(data.get("descripcion") or "").strip()
    if not data["descripcion"]:
        raise ValueError("La descripcion es obligatoria.")
    data["peso"] = _to_float(data.get("peso"), 1.0)
    if data["peso"] <= 0:
        raise ValueError("El peso debe ser mayor a cero.")
    data["puntaje_esperado"] = _to_int(data.get("puntaje_esperado"), 4)
    if data["puntaje_esperado"] < 1 or data["puntaje_esperado"] > 5:
        raise ValueError("El puntaje esperado debe estar entre 1 y 5.")
    data["puesto_id"] = _normalize_puesto_id(data)
    dup = get_pregunta_by_unique(
        int(data["sector_id"]),
        data["categoria"],
        data["descripcion"],
        puesto_id=data["puesto_id"],
        exclude_id=int(pregunta_id),
    )
    if dup:
        raise ValueError("Ya existe una pregunta igual para ese sector, puesto y categoria.")
    update_pregunta_row(int(pregunta_id), data)


def activar_pregunta(pregunta_id: int, activo: int) -> None:
    if not get_pregunta_by_id(int(pregunta_id)):
        raise ValueError("Pregunta no encontrada.")
    set_pregunta_activo(int(pregunta_id), int(activo))


def contar_preguntas(activo: int | None = None) -> int:
    return count_preguntas(activo=activo)


def get_evaluacion_detalle_pack(evaluacion_id: int) -> tuple[dict, list[dict], dict | None]:
    evaluacion = get_evaluacion_by_id(int(evaluacion_id))
    if not evaluacion:
        raise ValueError("Evaluacion no encontrada.")
    detalles = get_evaluacion_detalles(int(evaluacion_id))
    plan = get_plan_by_evaluacion_id(int(evaluacion_id))
    acciones = get_plan_actions(int(plan["id"])) if plan else []
    return evaluacion, detalles, (serialize_plan(plan, acciones) if plan else None)

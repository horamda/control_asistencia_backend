from __future__ import annotations

import csv
import datetime as _dt
import io
import unicodedata

from extensions import get_db
from repositories.puesto_repository import get_all as get_puestos
from repositories.sector_repository import get_all as get_sectores
from repositories.skap_pregunta_repository import create as create_pregunta
from repositories.skap_pregunta_repository import get_all_active_for_sector
from repositories.skap_pregunta_repository import get_by_unique
from repositories.skap_pregunta_repository import update as update_pregunta


BASE_QUESTIONS = [
    {
        "categoria": "S",
        "descripcion": "Aplica correctamente los procedimientos operativos definidos.",
        "peso": 1.20,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "S",
        "descripcion": "Resuelve situaciones del puesto con criterio tecnico y seguridad.",
        "peso": 1.10,
        "puntaje_esperado": 4,
        "requiere_observacion": True,
        "requiere_evidencia": False,
    },
    {
        "categoria": "S",
        "descripcion": "Utiliza herramientas, sistemas o equipos del sector de forma adecuada.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "K",
        "descripcion": "Conoce normas internas, politicas y criterios de calidad aplicables al puesto.",
        "peso": 1.10,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "K",
        "descripcion": "Comprende los objetivos del sector y su impacto en clientes internos o externos.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": True,
        "requiere_evidencia": False,
    },
    {
        "categoria": "K",
        "descripcion": "Mantiene actualizados los conocimientos necesarios para ejecutar sus tareas.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "A",
        "descripcion": "Demuestra compromiso, puntualidad y responsabilidad en el cumplimiento diario.",
        "peso": 1.20,
        "puntaje_esperado": 4,
        "requiere_observacion": True,
        "requiere_evidencia": False,
    },
    {
        "categoria": "A",
        "descripcion": "Colabora con el equipo y mantiene una comunicacion respetuosa.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "A",
        "descripcion": "Se adapta a cambios operativos manteniendo buena disposicion.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
    {
        "categoria": "P",
        "descripcion": "Cumple objetivos, tiempos y calidad esperada para el puesto.",
        "peso": 1.30,
        "puntaje_esperado": 4,
        "requiere_observacion": True,
        "requiere_evidencia": True,
    },
    {
        "categoria": "P",
        "descripcion": "Gestiona prioridades y sostiene productividad estable durante el periodo.",
        "peso": 1.10,
        "puntaje_esperado": 4,
        "requiere_observacion": True,
        "requiere_evidencia": False,
    },
    {
        "categoria": "P",
        "descripcion": "Registra, informa o documenta avances e incidentes de forma oportuna.",
        "peso": 1.00,
        "puntaje_esperado": 4,
        "requiere_observacion": False,
        "requiere_evidencia": False,
    },
]

_DELIMITERS = (",", ";", "\t")
_CATEGORIES = {"S", "K", "A", "P"}


def _normalize_key(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    raw = raw.encode("ascii", "ignore").decode("ascii")
    pieces = []
    last_sep = False
    for char in raw:
        if char.isalnum():
            pieces.append(char)
            last_sep = False
        elif not last_sep:
            pieces.append("_")
            last_sep = True
    return "".join(pieces).strip("_")


def _clean(row: dict, *keys: str, default=None):
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return default


def _parse_bool(value, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "si", "s", "on", "activo"}


def _parse_float(value, default: float = 1.0) -> float:
    raw = str(value if value is not None else "").strip().replace(",", ".")
    if not raw:
        return float(default)
    return float(raw)


def _parse_int(value, default: int | None = None) -> int | None:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return default
    return int(float(raw.replace(",", ".")))


def _normalize_payload(data: dict) -> dict:
    sector_id = _parse_int(data.get("sector_id"))
    if not sector_id:
        raise ValueError("sector_id es obligatorio.")

    categoria = str(data.get("categoria") or "").strip().upper()
    if categoria not in _CATEGORIES:
        raise ValueError("categoria debe ser S, K, A o P.")

    descripcion = str(data.get("descripcion") or "").strip()
    if not descripcion:
        raise ValueError("descripcion es obligatoria.")

    peso = _parse_float(data.get("peso"), 1.0)
    if peso <= 0:
        raise ValueError("peso debe ser mayor a cero.")

    puntaje_esperado = _parse_int(data.get("puntaje_esperado"), 4)
    if puntaje_esperado is None or puntaje_esperado < 1 or puntaje_esperado > 5:
        raise ValueError("puntaje_esperado debe estar entre 1 y 5.")

    puesto_id = _parse_int(data.get("puesto_id")) or None

    return {
        "sector_id": int(sector_id),
        "puesto_id": puesto_id,
        "categoria": categoria,
        "descripcion": descripcion,
        "peso": peso,
        "puntaje_esperado": int(puntaje_esperado),
        "requiere_observacion": _parse_bool(data.get("requiere_observacion"), False),
        "requiere_evidencia": _parse_bool(data.get("requiere_evidencia"), False),
        "activo": _parse_bool(data.get("activo"), True),
    }


def _sector_lookup():
    sectors = get_sectores(include_inactive=True)
    by_id = {int(row["id"]): row for row in sectors if row.get("id")}
    by_company_name: dict[tuple[int | None, str], list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for row in sectors:
        name = str(row.get("nombre") or "").strip().lower()
        if not name:
            continue
        by_name.setdefault(name, []).append(row)
        by_company_name.setdefault((row.get("empresa_id"), name), []).append(row)
    return sectors, by_id, by_name, by_company_name


def _resolve_sector_id(row: dict, by_id: dict, by_name: dict, by_company_name: dict) -> int:
    sector_id = _parse_int(_clean(row, "sector_id", "id_sector"))
    if sector_id:
        if sector_id not in by_id:
            raise ValueError(f"Sector {sector_id} no encontrado.")
        return sector_id

    sector_name = str(_clean(row, "sector", "sector_nombre", "nombre_sector", default="") or "").strip().lower()
    if not sector_name:
        raise ValueError("Debe indicar sector_id o sector_nombre.")

    empresa_id = _parse_int(_clean(row, "empresa_id", "id_empresa"))
    candidates = by_company_name.get((empresa_id, sector_name), []) if empresa_id else by_name.get(sector_name, [])
    if len(candidates) == 1:
        return int(candidates[0]["id"])
    if len(candidates) > 1:
        raise ValueError("sector_nombre es ambiguo; agregue empresa_id o use sector_id.")
    raise ValueError(f"Sector '{sector_name}' no encontrado.")


def _puesto_lookup():
    puestos = get_puestos(include_inactive=True)
    by_id = {int(row["id"]): row for row in puestos if row.get("id")}
    by_name: dict[str, list[dict]] = {}
    for row in puestos:
        name = str(row.get("nombre") or "").strip().lower()
        if not name:
            continue
        by_name.setdefault(name, []).append(row)
    return puestos, by_id, by_name


def _resolve_puesto_id(row: dict, by_id: dict, by_name: dict) -> int | None:
    puesto_id = _parse_int(_clean(row, "puesto_id", "id_puesto"))
    if puesto_id:
        if puesto_id not in by_id:
            raise ValueError(f"Puesto {puesto_id} no encontrado.")
        return puesto_id

    puesto_name = str(_clean(row, "puesto", "puesto_nombre", "nombre_puesto", default="") or "").strip().lower()
    if not puesto_name:
        return None

    candidates = by_name.get(puesto_name, [])
    if len(candidates) == 1:
        return int(candidates[0]["id"])
    if len(candidates) > 1:
        raise ValueError("puesto_nombre es ambiguo; use puesto_id.")
    raise ValueError(f"Puesto '{puesto_name}' no encontrado.")


def _upsert_question(payload: dict, *, reactivate: bool = False, dry_run: bool = False) -> tuple[int | None, str]:
    normalized = _normalize_payload(payload)
    existing = get_by_unique(
        int(normalized["sector_id"]),
        normalized["categoria"],
        normalized["descripcion"],
        puesto_id=normalized.get("puesto_id"),
    )
    if existing:
        if reactivate and not existing.get("activo"):
            if not dry_run:
                update_pregunta(int(existing["id"]), {**normalized, "activo": True})
            return int(existing["id"]), "reactivated" if not dry_run else "would_reactivate"
        return int(existing["id"]), "skipped"

    if dry_run:
        return None, "would_create"
    return int(create_pregunta(normalized)), "created"


def seed_base_questions(
    *,
    empresa_id: int | None = None,
    sector_ids: list[int] | None = None,
    include_inactive_sectors: bool = False,
    reactivate: bool = False,
    dry_run: bool = False,
) -> dict:
    sectors = get_sectores(include_inactive=include_inactive_sectors)
    sector_id_set = {int(value) for value in sector_ids or []}
    selected = []
    for sector in sectors:
        if empresa_id and int(sector.get("empresa_id") or 0) != int(empresa_id):
            continue
        if sector_id_set and int(sector.get("id") or 0) not in sector_id_set:
            continue
        selected.append(sector)

    result = {
        "sectores": len(selected),
        "preguntas_base": len(BASE_QUESTIONS),
        "creadas": 0,
        "omitidas": 0,
        "reactivadas": 0,
        "simuladas": 0,
        "errores": [],
        "detalle": [],
    }
    for sector in selected:
        for question in BASE_QUESTIONS:
            payload = {**question, "sector_id": int(sector["id"]), "activo": True}
            try:
                pregunta_id, status = _upsert_question(payload, reactivate=reactivate, dry_run=dry_run)
                if status == "created":
                    result["creadas"] += 1
                elif status == "skipped":
                    result["omitidas"] += 1
                elif status == "reactivated":
                    result["reactivadas"] += 1
                else:
                    result["simuladas"] += 1
                result["detalle"].append(
                    {
                        "sector_id": int(sector["id"]),
                        "sector_nombre": sector.get("nombre"),
                        "categoria": question["categoria"],
                        "descripcion": question["descripcion"],
                        "pregunta_id": pregunta_id,
                        "estado": status,
                    }
                )
            except Exception as exc:
                result["errores"].append(
                    {
                        "sector_id": int(sector["id"]),
                        "sector_nombre": sector.get("nombre"),
                        "descripcion": question["descripcion"],
                        "motivo": str(exc),
                    }
                )
    return result


def _parse_csv(text: str):
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError("El archivo CSV esta vacio.")

    header_line = None
    delimiter = ","
    for line in lines[:10]:
        if not line.strip():
            continue
        for candidate in _DELIMITERS:
            columns = {_normalize_key(value) for value in next(csv.reader([line], delimiter=candidate))}
            if "categoria" in columns and "descripcion" in columns:
                header_line = line
                delimiter = candidate
                break
        if header_line:
            break
    if not header_line:
        raise ValueError("El CSV debe incluir al menos categoria y descripcion.")

    header_index = lines.index(header_line)
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    return reader, header_index


def importar_preguntas_desde_csv(
    stream,
    *,
    reactivate: bool = False,
    dry_run: bool = False,
) -> dict:
    raw = stream.read()
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else str(raw or "")
    reader, header_index = _parse_csv(text)
    _sectors, by_id, by_name, by_company_name = _sector_lookup()
    _puestos, puesto_by_id, puesto_by_name = _puesto_lookup()

    result = {
        "total_filas": 0,
        "creadas": 0,
        "omitidas": 0,
        "reactivadas": 0,
        "simuladas": 0,
        "errores": 0,
        "detalle_errores": [],
    }
    for row_number, raw_row in enumerate(reader, start=header_index + 2):
        row = {_normalize_key(key): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(row.values()):
            continue
        result["total_filas"] += 1
        try:
            sector_id = _resolve_sector_id(row, by_id, by_name, by_company_name)
            puesto_id = _resolve_puesto_id(row, puesto_by_id, puesto_by_name)
            payload = {
                "sector_id": sector_id,
                "puesto_id": puesto_id,
                "categoria": _clean(row, "categoria"),
                "descripcion": _clean(row, "descripcion"),
                "peso": _clean(row, "peso", default=1),
                "puntaje_esperado": _clean(row, "puntaje_esperado", "esperado", default=4),
                "requiere_observacion": _clean(row, "requiere_observacion", "observacion_requerida", default="0"),
                "requiere_evidencia": _clean(row, "requiere_evidencia", "evidencia_requerida", default="0"),
                "activo": _clean(row, "activo", default="1"),
            }
            _pregunta_id, status = _upsert_question(payload, reactivate=reactivate, dry_run=dry_run)
            if status == "created":
                result["creadas"] += 1
            elif status == "skipped":
                result["omitidas"] += 1
            elif status == "reactivated":
                result["reactivadas"] += 1
            else:
                result["simuladas"] += 1
        except Exception as exc:
            result["errores"] += 1
            result["detalle_errores"].append(
                {
                    "fila": row_number,
                    "descripcion": _clean(row, "descripcion"),
                    "motivo": str(exc),
                }
            )
    return result


def _find_example_employee(*, sector_id: int | None = None, empleado_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["e.activo = 1", "e.reporta_a_empleado_id IS NOT NULL", "boss.activo = 1"]
        params: list = []
        if empleado_id:
            where.append("e.id = %s")
            params.append(int(empleado_id))
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(int(sector_id))
        cursor.execute(
            f"""
            SELECT
                e.id,
                e.legajo,
                e.apellido,
                e.nombre,
                e.sector_id,
                e.puesto_id,
                e.reporta_a_empleado_id,
                boss.legajo AS jefe_legajo,
                boss.apellido AS jefe_apellido,
                boss.nombre AS jefe_nombre
            FROM empleados e
            JOIN empleados boss ON boss.id = e.reporta_a_empleado_id
            WHERE {" AND ".join(where)}
            ORDER BY e.sector_id ASC, e.apellido ASC, e.nombre ASC, e.id ASC
            LIMIT 1
            """,
            tuple(params),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def build_example_evaluacion_payload(
    *,
    sector_id: int | None = None,
    empleado_id: int | None = None,
    anio: int | None = None,
) -> dict:
    employee = _find_example_employee(sector_id=sector_id, empleado_id=empleado_id)
    resolved_sector_id = sector_id or (int(employee["sector_id"]) if employee and employee.get("sector_id") else None)
    if not resolved_sector_id:
        raise ValueError("No hay sector para generar el ejemplo.")

    resolved_puesto_id = int(employee["puesto_id"]) if employee and employee.get("puesto_id") else None
    questions = get_all_active_for_sector(int(resolved_sector_id), puesto_id=resolved_puesto_id)
    if not questions:
        raise ValueError("No hay preguntas activas para el sector/puesto seleccionado.")

    scores_by_category = {"S": 4, "K": 4, "A": 5, "P": 4}
    respuestas = []
    for question in questions:
        categoria = str(question.get("categoria") or "").strip().upper()
        puntaje = scores_by_category.get(categoria, 4)
        respuestas.append(
            {
                "pregunta_id": int(question["id"]),
                "puntaje": puntaje,
                "observacion": f"Ejemplo inicial para {question.get('descripcion')}",
                "evidencia": "Evidencia operativa de ejemplo" if question.get("requiere_evidencia") else None,
            }
        )

    return {
        "endpoint": "/api/skap/evaluacion",
        "method": "POST",
        "authorization_hint": (
            f"Usar token del jefe directo empleado_id={employee['reporta_a_empleado_id']}"
            if employee
            else "Usar token de un supervisor, jefe, gerente, admin o rrhh."
        ),
        "empleado": {
            "id": employee.get("id") if employee else None,
            "legajo": employee.get("legajo") if employee else None,
            "nombre": (
                f"{employee.get('apellido')}, {employee.get('nombre')}"
                if employee
                else None
            ),
            "jefe_directo_id": employee.get("reporta_a_empleado_id") if employee else None,
            "jefe_directo": (
                f"{employee.get('jefe_apellido')}, {employee.get('jefe_nombre')}"
                if employee
                else None
            ),
        },
        "payload": {
            "empleado_id": employee.get("id") if employee else None,
            "anio": int(anio or _dt.date.today().year),
            "observaciones_generales": "Evaluacion anual SKAP de ejemplo.",
            "respuestas": respuestas,
        },
    }

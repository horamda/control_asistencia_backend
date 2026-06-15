import datetime
from collections import defaultdict

from repositories.legajo_evento_repository import get_eventos_by_empleado


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _to_date_str(value):
    date_value = _to_date(value)
    if date_value is not None:
        return date_value.isoformat()
    return None


def _to_datetime_str(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def legajo_adjunto_to_mobile_dict(row: dict) -> dict:
    adjunto_id = row.get("id")
    return {
        "id": adjunto_id,
        "evento_id": row.get("evento_id"),
        "nombre_original": row.get("nombre_original") or "",
        "mime_type": row.get("mime_type") or "application/octet-stream",
        "extension": row.get("extension"),
        "tamano_bytes": int(row.get("tamano_bytes") or 0),
        "estado": row.get("estado") or "activo",
        "created_at": _to_datetime_str(row.get("created_at")),
        "download_url": f"/api/v1/mobile/me/legajo/adjuntos/{adjunto_id}",
    }


def legajo_evento_to_mobile_dict(evento: dict, adjuntos: list[dict] | None = None) -> dict:
    return {
        "id": evento.get("id"),
        "empresa_id": evento.get("empresa_id"),
        "empleado_id": evento.get("empleado_id"),
        "tipo_id": evento.get("tipo_id"),
        "tipo_codigo": evento.get("tipo_codigo") or "",
        "tipo_nombre": evento.get("tipo_nombre") or "",
        "fecha_evento": _to_date_str(evento.get("fecha_evento")),
        "fecha_desde": _to_date_str(evento.get("fecha_desde")),
        "fecha_hasta": _to_date_str(evento.get("fecha_hasta")),
        "titulo": evento.get("titulo") or "",
        "descripcion": evento.get("descripcion") or "",
        "estado": evento.get("estado") or "vigente",
        "severidad": evento.get("severidad"),
        "justificacion_id": evento.get("justificacion_id"),
        "adjuntos_count": int(evento.get("adjuntos_count") or 0),
        "created_at": _to_datetime_str(evento.get("created_at")),
        "updated_at": _to_datetime_str(evento.get("updated_at")),
    }


def legajo_tipo_evento_to_mobile_dict(tipo: dict) -> dict:
    return {
        "id": tipo.get("id"),
        "codigo": tipo.get("codigo") or "",
        "nombre": tipo.get("nombre") or "",
        "requiere_rango_fechas": bool(tipo.get("requiere_rango_fechas")),
        "permite_adjuntos": bool(tipo.get("permite_adjuntos")),
        "activo": bool(tipo.get("activo")),
    }


def calcular_resumen_legajo(empleado_id: int, desde: datetime.date, hasta: datetime.date) -> dict:
    eventos = get_eventos_by_empleado(int(empleado_id), include_anulados=True)

    historico_vigentes = sum(
        1 for evento in eventos
        if str(evento.get("estado") or "").strip().lower() == "vigente"
    )
    historico_anulados = len(eventos) - historico_vigentes

    eventos_periodo = []
    for evento in eventos:
        fecha_evento = _to_date(evento.get("fecha_evento"))
        if (
            fecha_evento is not None
            and desde <= fecha_evento <= hasta
            and str(evento.get("estado") or "").strip().lower() == "vigente"
        ):
            eventos_periodo.append(evento)

    tipo_counts = defaultdict(lambda: {"label": "", "total": 0})
    severidad_counts = defaultdict(int)
    for evento in eventos_periodo:
        tipo_id = evento.get("tipo_id")
        tipo_counts[tipo_id]["label"] = (
            evento.get("tipo_nombre")
            or evento.get("tipo_codigo")
            or str(tipo_id or "sin_tipo")
        )
        tipo_counts[tipo_id]["total"] += 1
        severidad = str(evento.get("severidad") or "").strip().lower() or "sin_severidad"
        severidad_counts[severidad] += 1

    total_tipo = sum(item["total"] for item in tipo_counts.values()) or 1
    total_severidad = sum(severidad_counts.values()) or 1

    recientes = sorted(
        eventos_periodo,
        key=lambda evento: (_to_date(evento.get("fecha_evento")) or datetime.date.min, evento.get("id") or 0),
        reverse=True,
    )[:5]

    return {
        "historico": {
            "total": len(eventos),
            "vigentes": historico_vigentes,
            "anulados": historico_anulados,
        },
        "periodo": {
            "total": len(eventos_periodo),
            "graves": sum(1 for e in eventos_periodo if str(e.get("severidad") or "").lower() == "grave"),
            "media": sum(1 for e in eventos_periodo if str(e.get("severidad") or "").lower() == "media"),
            "leve": sum(1 for e in eventos_periodo if str(e.get("severidad") or "").lower() == "leve"),
            "sin_severidad": sum(1 for e in eventos_periodo if not str(e.get("severidad") or "").strip()),
        },
        "por_tipo": sorted(
            [
                {
                    "label": item["label"],
                    "total": item["total"],
                    "pct": round(item["total"] * 100 / total_tipo, 1),
                }
                for item in tipo_counts.values()
            ],
            key=lambda item: (-item["total"], item["label"]),
        ),
        "por_severidad": [
            {
                "severidad": severidad,
                "total": total,
                "pct": round(total * 100 / total_severidad, 1),
            }
            for severidad, total in sorted(severidad_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recientes": [legajo_evento_to_mobile_dict(evento) for evento in recientes],
    }

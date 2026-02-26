import json
from decimal import Decimal

from extensions import get_db


def create_geo_qr_rechazo(
    *,
    empleado_id: int,
    empresa_id: int,
    fecha_operacion: str | None,
    hora_operacion: str | None,
    lat: float | None,
    lon: float | None,
    ref_lat: float | None,
    ref_lon: float | None,
    distancia_m: float | None,
    tolerancia_m: float | None,
    sucursal_id: int | None,
    qr_accion: str | None,
    qr_scope: str | None,
    qr_empresa_id: int | None,
    payload: dict | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        cursor.execute(
            """
            INSERT INTO eventos_seguridad (
                empleado_id,
                empresa_id,
                tipo_evento,
                severidad,
                fecha_operacion,
                hora_operacion,
                lat,
                lon,
                ref_lat,
                ref_lon,
                distancia_m,
                tolerancia_m,
                sucursal_id,
                qr_accion,
                qr_scope,
                qr_empresa_id,
                alerta_fraude,
                payload_json
            ) VALUES (%s,%s,'qr_geo_fuera_rango','alta',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)
            """,
            (
                empleado_id,
                empresa_id,
                fecha_operacion,
                hora_operacion,
                lat,
                lon,
                ref_lat,
                ref_lon,
                distancia_m,
                tolerancia_m,
                sucursal_id,
                qr_accion,
                qr_scope,
                qr_empresa_id,
                payload_json,
            ),
        )
        db.commit()
        return int(cursor.lastrowid)
    finally:
        cursor.close()
        db.close()


def get_page_by_empleado(
    empleado_id: int,
    page: int,
    per_page: int,
    tipo_evento: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = "WHERE empleado_id = %s"
        params: list = [empleado_id]
        if tipo_evento:
            where += " AND tipo_evento = %s"
            params.append(tipo_evento)

        cursor.execute(
            f"""
            SELECT
                id,
                tipo_evento,
                severidad,
                fecha,
                fecha_operacion,
                hora_operacion,
                lat,
                lon,
                ref_lat,
                ref_lon,
                distancia_m,
                tolerancia_m,
                sucursal_id,
                alerta_fraude
            FROM eventos_seguridad
            {where}
            ORDER BY fecha DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [per_page, offset]),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM eventos_seguridad
            {where}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"])
        return [_normalize_row(r) for r in rows], total
    finally:
        cursor.close()
        db.close()


def _normalize_row(row: dict):
    out = dict(row)
    numeric_fields = (
        "lat",
        "lon",
        "ref_lat",
        "ref_lon",
        "distancia_m",
        "tolerancia_m",
    )
    for key in numeric_fields:
        value = out.get(key)
        if isinstance(value, Decimal):
            out[key] = float(value)
    if out.get("alerta_fraude") is not None:
        out["alerta_fraude"] = bool(out["alerta_fraude"])
    return out

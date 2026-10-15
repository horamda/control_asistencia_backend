"""Egreso automatico por olvido de fichada.

Cierra las jornadas de dias anteriores que tienen ingreso y no tienen egreso:
- hora de egreso: fin del bloque del horario asignado que contiene (o sigue a)
  el ingreso; sin horario ese dia, ingreso + N horas (parametro por empresa);
  siempre con tope a las 23:59 del mismo dia (las jornadas no cruzan la medianoche).
- la marca queda con metodo "automatico": cuenta como horas trabajadas y como
  error en la efectividad de fichaje del empleado.
"""
import datetime as dt
import re
import logging

from extensions import get_db
from repositories import asistencia_marca_repository
from utils.asistencia import get_horario_esperado

ARGENTINA = dt.timezone(dt.timedelta(hours=-3))
METODO = "automatico"
HORAS_DEFAULT = 8.0
FIN_DEL_DIA = 23 * 60 + 59

logger = logging.getLogger(__name__)


def _minutes(value):
    if value is None:
        return None
    if isinstance(value, dt.timedelta):  # MySQL TIME
        return int(value.total_seconds() // 60)
    if isinstance(value, (dt.time, dt.datetime)):
        return value.hour * 60 + value.minute
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _hhmmss(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def calcular_egreso(hora_entrada, bloques, horas=HORAS_DEFAULT):
    """Devuelve (hora 'HH:MM:SS', origen 'horario'|'parametro')."""
    entrada = _minutes(hora_entrada)
    ordenados = sorted(
        (b for b in bloques or [] if b.get("salida")),
        key=lambda b: _minutes(b.get("entrada")) or 0,
    )
    for bloque in ordenados:
        fin = _minutes(bloque.get("salida"))
        if fin > entrada:
            return _hhmmss(min(fin, FIN_DEL_DIA)), "horario"
    return _hhmmss(max(entrada, min(entrada + round(float(horas) * 60), FIN_DEL_DIA))), "parametro"


def _configuraciones(cursor):
    cursor.execute(
        "SELECT empresa_id, egreso_automatico_activo, egreso_automatico_horas FROM configuracion_empresa"
    )
    return {
        row["empresa_id"]: (bool(row["egreso_automatico_activo"]), float(row["egreso_automatico_horas"]))
        for row in cursor.fetchall()
    }


def _bloques(empleado_id, fecha):
    try:
        esperado = get_horario_esperado(empleado_id, fecha.isoformat())
    except Exception:
        logger.warning("egreso_automatico_horario_error", exc_info=True)
        return []
    return (esperado or {}).get("bloques") or []


def _cerrar(asistencia_id, hora, origen, horas):
    """Cierra una jornada si sigue abierta. Devuelve True si la cerro."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute("SELECT * FROM asistencias WHERE id = %s FOR UPDATE", (asistencia_id,))
        row = cursor.fetchone()
        if not row or row.get("hora_entrada") is None or row.get("hora_salida") is not None:
            db.rollback()
            return False
        detalle = "segun horario asignado" if origen == "horario" else f"ingreso + {horas:g} h"
        nota = f"Egreso automatico por olvido de fichada ({detalle})."
        cursor.execute(
            "SELECT 1 FROM asistencia_marcas WHERE empleado_id = %s AND fecha = %s LIMIT 1",
            (row["empleado_id"], row["fecha"]),
        )
        # Sin marcas (jornada cargada a mano) se cierra solo el resumen: una marca
        # suelta de egreso ocultaria el ingreso en el reporte de marcas.
        if cursor.fetchone():
            asistencia_marca_repository.create(
                empresa_id=row["empresa_id"], empleado_id=row["empleado_id"], fecha=row["fecha"],
                hora=hora, accion="egreso", metodo=METODO, tipo_marca="jornada",
                lat=None, lon=None, foto=None, gps_ok=None, gps_distancia_m=None,
                gps_tolerancia_m=None, gps_ref_lat=None, gps_ref_lon=None,
                estado=row.get("estado"), observaciones=nota, asistencia_id=asistencia_id, _db=db,
            )
        cursor.execute(
            """
            UPDATE asistencias
            SET hora_salida = %s,
                metodo_salida = %s,
                observaciones = CONCAT_WS(' | ', NULLIF(observaciones, ''), %s)
            WHERE id = %s
            """,
            (hora, METODO, nota, asistencia_id),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


_DETALLE_PARAMETRO = re.compile(r"ingreso \+ [0-9]+(?:\.[0-9]+)? h")


def recalcular_por_parametro(*, empresa_id=None, dry_run=False):
    """Recalcula las jornadas cerradas por horas configuradas con el valor actual de cada empresa
    (p. ej. tras cambiar el parametro). Las cerradas segun horario asignado no se tocan.
    Devuelve {revisadas, cambiadas, sin_cambios, detalle: [(id, salida_anterior, salida_nueva)]}."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    resumen = {"revisadas": 0, "cambiadas": 0, "sin_cambios": 0, "detalle": []}
    try:
        if not dry_run:
            db.start_transaction()  # todo o nada
        configs = _configuraciones(cursor)
        sql = ("SELECT id, empresa_id, hora_entrada, hora_salida, observaciones FROM asistencias "
               "WHERE metodo_salida = %s AND observaciones LIKE %s")
        params = [METODO, "%Egreso automatico por olvido de fichada (ingreso + %"]
        if empresa_id:
            sql += " AND empresa_id = %s"
            params.append(int(empresa_id))
        cursor.execute(sql + " ORDER BY id", tuple(params))
        filas = cursor.fetchall()
        for row in filas:
            resumen["revisadas"] += 1
            horas = configs.get(row["empresa_id"], (True, HORAS_DEFAULT))[1]
            nueva, _ = calcular_egreso(row["hora_entrada"], [], horas)
            anterior = _hhmmss(_minutes(row["hora_salida"]))
            detalle = f"ingreso + {horas:g} h"
            observaciones = _DETALLE_PARAMETRO.sub(detalle, row["observaciones"], count=1)
            if anterior == nueva:
                resumen["sin_cambios"] += 1  # p. ej. topes a las 23:59: solo se actualiza la nota
                if observaciones == row["observaciones"]:
                    continue
            else:
                resumen["cambiadas"] += 1
                resumen["detalle"].append((row["id"], anterior, nueva))
            if dry_run:
                continue
            cursor.execute("UPDATE asistencias SET hora_salida = %s, observaciones = %s WHERE id = %s",
                           (nueva, observaciones, row["id"]))
            cursor.execute(
                "UPDATE asistencia_marcas SET hora = %s, observaciones = %s"
                " WHERE asistencia_id = %s AND accion = 'egreso' AND metodo = %s",
                (nueva, f"Egreso automatico por olvido de fichada ({detalle}).", row["id"], METODO),
            )
        if not dry_run:
            db.commit()
    except Exception:
        if not dry_run:
            db.rollback()
        raise
    finally:
        cursor.close()
        db.close()
    return resumen


def _ahora():
    return dt.datetime.now(ARGENTINA).replace(tzinfo=None)


def _registrar_ejecucion(resumen, origen, usuario_id, inicio):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO egreso_automatico_ejecuciones
            (origen, usuario_id, inicio, fin, revisadas, cerradas, por_horario, por_parametro, empresa_desactivada, errores)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (origen, usuario_id, inicio, _ahora(), resumen["revisadas"], resumen["cerradas"], resumen["por_horario"],
             resumen["por_parametro"], resumen["empresa_desactivada"], resumen["errores"]),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def cerrar_jornadas_abiertas(*, hoy=None, empresa_id=None, limite=None, dry_run=False,
                             origen="nocturno", usuario_id=None):
    """Cierra las jornadas abiertas de dias anteriores a hoy (hora Argentina).
    origen: nocturno | inicio | manual (queda en el historial de ejecuciones)."""
    inicio = _ahora()
    hoy = hoy or inicio.date()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        configs = _configuraciones(cursor)
        sql = (
            "SELECT id, empresa_id, empleado_id, fecha, hora_entrada FROM asistencias "
            "WHERE hora_entrada IS NOT NULL AND hora_salida IS NULL AND fecha < %s"
        )
        params = [hoy]
        if empresa_id:
            sql += " AND empresa_id = %s"
            params.append(int(empresa_id))
        sql += " ORDER BY fecha, id"
        if limite:
            sql += " LIMIT %s"
            params.append(int(limite))
        cursor.execute(sql, tuple(params))
        abiertas = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    resumen = {"revisadas": len(abiertas), "cerradas": 0, "por_horario": 0, "por_parametro": 0,
               "empresa_desactivada": 0, "errores": 0, "detalle": []}
    for row in abiertas:
        activo, horas = configs.get(row["empresa_id"], (True, HORAS_DEFAULT))
        if not activo:
            resumen["empresa_desactivada"] += 1
            continue
        hora, fuente = calcular_egreso(row["hora_entrada"], _bloques(row["empleado_id"], row["fecha"]), horas)
        if dry_run:
            cerrada = True
        else:
            try:
                cerrada = _cerrar(row["id"], hora, fuente, horas)
            except Exception:
                logger.exception("egreso_automatico_error", extra={"extra": {"asistencia_id": row["id"]}})
                resumen["errores"] += 1
                continue
        if cerrada:
            resumen["cerradas"] += 1
            resumen["por_" + fuente] += 1
            if len(resumen["detalle"]) < 50:
                resumen["detalle"].append({"asistencia_id": row["id"], "fecha": str(row["fecha"]),
                                           "entrada": str(row["hora_entrada"]), "egreso": hora, "origen": fuente})
    logger.info("egreso_automatico", extra={"extra": {k: v for k, v in resumen.items() if k != "detalle"}})
    if not dry_run:
        try:
            _registrar_ejecucion(resumen, origen, usuario_id, inicio)
        except Exception:
            logger.warning("egreso_automatico_historial_error", exc_info=True)
    return resumen


def pendientes(*, hoy=None, empresa_id=None):
    """Jornadas de dias anteriores que todavia no tienen egreso."""
    hoy = hoy or _ahora().date()
    sql = ("SELECT COUNT(*) AS n FROM asistencias WHERE hora_entrada IS NOT NULL "
           "AND hora_salida IS NULL AND fecha < %s")
    params = [hoy]
    if empresa_id:
        sql += " AND empresa_id = %s"
        params.append(int(empresa_id))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(sql, tuple(params))
        return int((cursor.fetchone() or {}).get("n") or 0)
    finally:
        cursor.close()
        db.close()


def ejecuciones(limite=15):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT x.*, u.usuario AS usuario_nombre
            FROM egreso_automatico_ejecuciones x
            LEFT JOIN usuarios u ON u.id = x.usuario_id
            ORDER BY x.inicio DESC, x.id DESC
            LIMIT %s
            """,
            (int(limite),),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def cerradas_page(*, page=1, per_page=20, desde=None, hasta=None, q=None, empresa_id=None):
    """Jornadas cerradas por el sistema, mas recientes primero."""
    where = ["a.metodo_salida = %s"]
    params = [METODO]
    if desde:
        where.append("a.fecha >= %s")
        params.append(desde)
    if hasta:
        where.append("a.fecha <= %s")
        params.append(hasta)
    if empresa_id:
        where.append("a.empresa_id = %s")
        params.append(int(empresa_id))
    if q:
        like = f"%{q.strip()}%"
        where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.legajo LIKE %s OR e.dni LIKE %s)")
        params.extend([like, like, like, like])
    where_sql = " AND ".join(where)
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT a.id, a.fecha, a.hora_entrada, a.hora_salida, a.observaciones,
                   e.id AS empleado_id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            LEFT JOIN sectores s ON s.id = e.sector_id
            WHERE {where_sql}
            ORDER BY a.fecha DESC, a.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), (max(1, int(page)) - 1) * int(per_page)),
        )
        rows = cursor.fetchall()
        cursor.execute(
            f"SELECT COUNT(*) AS n FROM asistencias a JOIN empleados e ON e.id = a.empleado_id WHERE {where_sql}",
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("n") or 0)
    finally:
        cursor.close()
        db.close()
    for row in rows:
        row["origen"] = "horario" if "horario asignado" in (row.get("observaciones") or "") else "parametro"
    return rows, total


def efectividad_por_empleado(empleado_ids, desde, hasta):
    """{empleado_id: {jornadas, olvidos, efectividad_pct}} en el periodo.
    Efectividad = jornadas con egreso fichado por el empleado / jornadas con ingreso."""
    ids = [int(i) for i in empleado_ids if i]
    if not ids:
        return {}
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT empleado_id,
                   COUNT(*) AS jornadas,
                   COALESCE(SUM(metodo_salida = %s), 0) AS olvidos
            FROM asistencias
            WHERE empleado_id IN ({", ".join(["%s"] * len(ids))})
              AND fecha BETWEEN %s AND %s
              AND hora_entrada IS NOT NULL
              AND hora_salida IS NOT NULL
            GROUP BY empleado_id
            """,
            (METODO, *ids, desde, hasta),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        db.close()
    resultado = {}
    for row in rows:
        jornadas, olvidos = int(row["jornadas"] or 0), int(row["olvidos"] or 0)
        resultado[int(row["empleado_id"])] = {
            "jornadas": jornadas,
            "olvidos": olvidos,
            "efectividad_pct": round((jornadas - olvidos) * 100.0 / jornadas, 1) if jornadas else None,
        }
    return resultado


def efectividad_empleado(empleado_id, desde, hasta):
    return efectividad_por_empleado([empleado_id], desde, hasta).get(
        int(empleado_id), {"jornadas": 0, "olvidos": 0, "efectividad_pct": None}
    )

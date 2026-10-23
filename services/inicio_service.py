"""Inicio del panel: lo que hay que mirar o resolver hoy, con pocas consultas.

Las estadisticas completas (rankings, comparativas, horas, riesgo) estan en Asistencia -> Estadisticas
(web/dashboard_metrics.py). Aca se usan los mismos criterios que alli para que los numeros coincidan, pero el filtro de
empresa y sucursal se aplica a todos.

Cada bloque depende de un permiso: los numeros de asistencia, del modulo asistencias; cada pendiente, del modulo que
lo resuelve. Un error en un bloque no rompe el inicio: ese bloque queda vacio y se registra en el log."""
import datetime as dt

from flask import current_app

from extensions import get_db
from web.dashboard_metrics import _EN_PERIODO_ASISTENCIA

# (clave, modulo con permiso, titulo, descripcion, SQL que cuenta, ruta del listado)
# El SQL recibe el alcance como "{alcance}" sobre el alias e (empleados).
PENDIENTES = [
    ("justificaciones", "justificaciones", "Justificaciones", "Para aprobar o rechazar",
     """SELECT COUNT(*) FROM justificaciones j JOIN empleados e ON e.id = j.empleado_id
        WHERE (j.estado = 'pendiente' OR j.estado IS NULL) {alcance}""", "/justificaciones/?estado=pendiente"),
    ("vacaciones", "vacaciones", "Vacaciones", "Pedidos sin resolver",
     """SELECT COUNT(*) FROM vacaciones_movimientos vm JOIN empleados e ON e.id = vm.empleado_id
        WHERE vm.estado = 'pendiente' AND vm.revertido_por_movimiento_id IS NULL AND vm.origen_movimiento_id IS NULL
        {alcance}""", "/vacaciones/?estado=pendiente"),
    ("horas_extras", "horas_extras", "Horas extras", "Con visto bueno del jefe, esperan a RR. HH.",
     """SELECT COUNT(*) FROM jl_horas_extra x JOIN empleados e ON e.id = x.empleado_id
        WHERE (x.estado = 'visto_jefe' OR (x.estado = 'rechazada' AND x.resuelto_por IS NULL)) {alcance}""",
     "/horas-extras/"),
    ("adelantos", "pedidos_empleados", "Adelantos", "Para pagar o rechazar",
     """SELECT COUNT(*) FROM adelantos ad JOIN empleados e ON e.id = ad.empleado_id
        WHERE (ad.estado = 'pendiente' OR ad.estado IS NULL) {alcance}""", "/adelantos/?estado=pendiente"),
    ("pedidos_mercaderia", "pedidos_empleados", "Pedidos de mercadería", "Para aprobar",
     """SELECT COUNT(*) FROM pedidos_mercaderia pm JOIN empleados e ON e.id = pm.empleado_id
        WHERE (pm.estado = 'pendiente' OR pm.estado IS NULL) {alcance}""", "/pedidos-mercaderia/?estado=pendiente"),
    ("reintegros", "reintegros", "Viáticos y reintegros", "Rendiciones enviadas",
     """SELECT COUNT(*) FROM reintegro_solicitudes r JOIN empleados e ON e.id = r.empleado_id
        WHERE r.estado = 'pendiente' {alcance}""", "/reintegros/"),
    ("epp", "epp", "Pedidos de EPP", "Para revisar",
     """SELECT COUNT(*) FROM epp_pedidos p JOIN empleados e ON e.id = p.empleado_id
        WHERE p.estado = 'pendiente' {alcance}""", "/epp/"),
    ("seguridad", "seguridad_higiene", "Reportes de seguridad", "Para aprobar o rechazar",
     """SELECT COUNT(*) FROM sh_eventos s LEFT JOIN empleados e ON e.id = s.reportante_id
        WHERE s.estado = 'pendiente' {alcance_sh}""", "/seguridad-higiene/"),
]


def _alcance(empresa_id, sucursal_id):
    sql, args = "", []
    if empresa_id:
        sql += " AND e.empresa_id = %s"
        args.append(int(empresa_id))
    if sucursal_id:
        sql += " AND e.sucursal_id = %s"
        args.append(int(sucursal_id))
    return sql, args


def _pct(parte, total):
    return round(parte * 100.0 / total, 1) if total else 0.0


def _asistencia(cursor, hoy, empresa_id, sucursal_id):
    """Hoy y el mes en curso, con los mismos criterios que Estadisticas."""
    alcance, args = _alcance(empresa_id, sucursal_id)
    mes_desde = hoy.replace(day=1)
    cursor.execute(f"""SELECT COUNT(*) FROM empleados e
                       WHERE e.activo = 1 AND COALESCE(e.requiere_control_asistencia, 1) = 1 {alcance}""", tuple(args))
    dotacion = int(cursor.fetchone()[0] or 0)
    cursor.execute(f"""SELECT COUNT(DISTINCT CASE WHEN a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL
                                                  THEN a.empleado_id END),
                              COUNT(CASE WHEN a.estado = 'tarde' THEN 1 END),
                              COUNT(CASE WHEN a.estado = 'ausente' THEN 1 END)
                       FROM asistencias a JOIN empleados e ON e.id = a.empleado_id AND {_EN_PERIODO_ASISTENCIA}
                       WHERE a.fecha = %s AND COALESCE(e.requiere_control_asistencia, 1) = 1 {alcance}""",
                   (hoy, *args))
    presentes, tarde_hoy, ausentes_hoy = (int(v or 0) for v in cursor.fetchone())
    cursor.execute(f"""SELECT COUNT(*),
                              COUNT(CASE WHEN a.estado = 'tarde' THEN 1 END),
                              COUNT(CASE WHEN a.estado = 'ausente' THEN 1 END),
                              COUNT(CASE WHEN a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL THEN 1 END),
                              COUNT(CASE WHEN (a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL)
                                          AND a.estado = 'ok' THEN 1 END),
                              COUNT(CASE WHEN a.estado = 'ausente' AND NOT EXISTS (
                                  SELECT 1 FROM justificaciones j WHERE j.empleado_id = a.empleado_id
                                    AND COALESCE(j.fecha_desde, j.fecha) <= a.fecha
                                    AND COALESCE(j.fecha_hasta, j.fecha) >= a.fecha AND j.estado = 'aprobada')
                                    THEN 1 END)
                       FROM asistencias a JOIN empleados e ON e.id = a.empleado_id AND {_EN_PERIODO_ASISTENCIA}
                       WHERE a.fecha BETWEEN %s AND %s {alcance}""", (mes_desde, hoy, *args))
    registros, tardes, ausentes, fichadas, a_tiempo, sin_justificar = (int(v or 0) for v in cursor.fetchone())
    return dict(
        hoy=dict(dotacion=dotacion, presentes=presentes, presentismo_pct=_pct(presentes, dotacion),
                 tarde=tarde_hoy, ausentes=ausentes_hoy),
        mes=dict(ausentismo_pct=_pct(ausentes, registros), puntualidad_pct=_pct(a_tiempo, fichadas),
                 ausentes=ausentes, sin_justificar=sin_justificar, sin_justificar_pct=_pct(sin_justificar, ausentes),
                 tardes=tardes),
    )


def _pendientes(cursor, puede, empresa_id, sucursal_id):
    alcance, args = _alcance(empresa_id, sucursal_id)
    # Los reportes de seguridad pueden ser de personas externas (sin empleado): el alcance va por la empresa del reporte.
    alcance_sh, args_sh = ("", [])
    if empresa_id:
        alcance_sh, args_sh = " AND s.empresa_id = %s", [int(empresa_id)]
    if sucursal_id:
        alcance_sh += " AND e.sucursal_id = %s"
        args_sh.append(int(sucursal_id))
    filas = []
    for clave, modulo, titulo, descripcion, sql, ruta in PENDIENTES:
        if not puede(modulo):
            continue
        try:
            cursor.execute(sql.format(alcance=alcance, alcance_sh=alcance_sh),
                           tuple(args_sh if clave == "seguridad" else args))
            cantidad = int(cursor.fetchone()[0] or 0)
        except Exception:
            current_app.logger.warning("inicio_pendiente_error", extra={"extra": {"clave": clave}}, exc_info=True)
            continue
        filas.append(dict(clave=clave, titulo=titulo, descripcion=descripcion, cantidad=cantidad, ruta=ruta))
    return filas


def resumen(*, puede, empresa_id=None, sucursal_id=None, hoy=None):
    """puede(modulo) -> bool con los permisos del usuario. Devuelve asistencia (o None sin permiso o si fallo) y la
    lista de pendientes de los modulos que puede ver."""
    hoy = hoy or dt.date.today()
    db = get_db()
    cursor = db.cursor()
    try:
        asistencia = None
        if puede("asistencias"):
            try:
                asistencia = _asistencia(cursor, hoy, empresa_id, sucursal_id)
            except Exception:
                current_app.logger.warning("inicio_asistencia_error", exc_info=True)
        return dict(asistencia=asistencia, pendientes=_pendientes(cursor, puede, empresa_id, sucursal_id))
    finally:
        cursor.close()
        db.close()


def presencia(*, empresa_id=None, sucursal_id=None):
    """Quien esta ahora en cada sucursal (los mismos numeros que la pantalla Presencia en vivo, sin nombres)."""
    from services.presencia_service import build_presence

    datos = build_presence(empresa_id)
    sucursales = [dict(nombre=b["nombre"], empresa=b["empresa"], empleados=b["empleados"], presentes=b["presentes"],
                       vinieron=b["vinieron"], retirados=b["retirados"], sin_ingreso=b["sin_ingreso"])
                  for b in datos["sucursales"] if not sucursal_id or b["id"] == sucursal_id]
    totales = {k: sum(b[k] for b in sucursales) for k in ("empleados", "presentes", "vinieron", "retirados", "sin_ingreso")}
    return dict(sucursales=sucursales, totales=totales, varias_empresas=len({b["empresa"] for b in sucursales}) > 1,
                actualizado=datos["actualizado"][11:16])

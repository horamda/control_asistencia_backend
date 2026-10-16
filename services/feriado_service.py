"""Dias no laborables para las reuniones: el mismo calendario del reporte mensual de asistencia
(asistencia_dias_no_laborables). No hay una carga aparte.

Alcances que mueven una reunion: (0, 0, 0) general, (empresa, 0, 0) y (empresa, sucursal, 0). Los
marcados para un solo sector se usan en los reportes pero no mueven una reunion entera."""

from repositories import carga_repository as db

SIN_NOMBRE = "Día no laborable"


def mapa(c, empresa_id):
    """{sucursal_id: {fecha: nombre}}; la clave 0 aplica a todas las sucursales."""
    salida = {}
    for row in db.all_rows(c, """SELECT d.sucursal_id, d.fecha, d.motivo FROM asistencia_dias_no_laborables d
                                 WHERE ((d.empresa_id = 0 AND d.sucursal_id = 0) OR d.empresa_id = %s)
                                   AND d.sector_id = 0""", (empresa_id,)):
        salida.setdefault(int(row["sucursal_id"] or 0), {})[row["fecha"]] = row["motivo"] or SIN_NOMBRE
    return salida


def de_sucursal(mapa_feriados, sucursal_id):
    """Dias no laborables que aplican a una sucursal (los generales mas los propios)."""
    feriados = dict(mapa_feriados.get(0, {}))
    if sucursal_id:
        feriados.update(mapa_feriados.get(int(sucursal_id), {}))
    return feriados


def reprogramar(c, empresa_id, desde):
    """Las fechas futuras de reuniones sin registros se recalculan con el calendario nuevo.
    empresa_id None (o 0) = todas las empresas."""
    sql = """DELETE o FROM reunion_ocurrencias o WHERE o.estado='programada' AND o.reprogramada = 0 AND o.fecha >= %s
             AND NOT EXISTS (SELECT 1 FROM reunion_asistencias a WHERE a.ocurrencia_id=o.id)"""
    args = [desde]
    if empresa_id:
        sql += " AND o.empresa_id=%s"
        args.append(int(empresa_id))
    try:
        c.execute(sql, tuple(args))
    except Exception as exc:  # instalaciones sin el modulo de reuniones
        if getattr(exc, "errno", None) != 1146:
            raise


def reprogramar_reuniones(empresa_id, desde):
    """Se llama al guardar el calendario del reporte mensual."""
    with db.transaction() as c:
        reprogramar(c, empresa_id, desde)

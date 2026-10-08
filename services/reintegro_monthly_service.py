"""Monthly rules shared by mobile, administration and reminders."""

import re
from datetime import date, timedelta
from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local, positive_int


def period(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise Error("Período obligatorio: AAAA-MM.")
    try:
        result = date.fromisoformat(value + "-01")
    except ValueError:
        raise Error("Período inválido.")
    if result.year < 2000 or result > now_local().date().replace(day=1):
        raise Error("El período no puede ser futuro ni anterior a 2000.")
    return result


def deadline(month):
    return (month.replace(day=28) + timedelta(days=4)).replace(day=15)


def enabled(c, employee):
    return bool(
        db.one(
            c,
            "SELECT h.sector_id FROM reintegro_sectores h JOIN sectores s ON s.id=h.sector_id AND s.empresa_id=h.empresa_id WHERE h.empresa_id=%s AND h.sector_id=%s AND s.activo=1",
            (employee["empresa_id"], employee.get("sector_id")),
        )
    )


def employee_write(c, employee, month, row=None):
    if not enabled(c, employee):
        raise Error(
            "Su sector no está habilitado para cargar viáticos. Puede consultar su historial.",
            403,
        )
    if month is None:
        return  # legacy history retains its original rules
    last = (
        max(deadline(month), row["reabierto_hasta"])
        if row and row.get("reabierto_hasta")
        else deadline(month)
    )
    if now_local().date() > last:
        raise Error(
            "El período está cerrado. Solicite una reapertura con plazo al administrador.",
            403,
        )


def settings(company):
    with db.transaction(read_only=True) as c:
        config = db.one(
            c, "SELECT revision FROM reintegro_config WHERE empresa_id=%s", (company,)
        )
        sectors = db.all_rows(
            c,
            """SELECT s.id,s.nombre,s.activo,CASE WHEN r.sector_id IS NULL THEN 0 ELSE 1 END habilitado
            FROM sectores s LEFT JOIN reintegro_sectores r ON r.sector_id=s.id AND r.empresa_id=s.empresa_id
            WHERE s.empresa_id=%s ORDER BY s.nombre""",
            (company,),
        )
    return dict(revision=config["revision"] if config else 0, sectores=sectors)


def save_settings(company, user, ids, revision):
    from services.reintegro_service import audit

    selected = {positive_int(v, "Sector") for v in ids}
    with db.transaction() as c:
        c.execute(
            "INSERT IGNORE INTO reintegro_config(empresa_id) VALUES(%s)", (company,)
        )
        old = db.one(
            c,
            "SELECT revision FROM reintegro_config WHERE empresa_id=%s FOR UPDATE",
            (company,),
        )
        if str(old["revision"]) != str(revision):
            raise Error("La configuración cambió. Recargue la página.", 409)
        valid = {
            r["id"]
            for r in db.all_rows(
                c,
                "SELECT id FROM sectores WHERE empresa_id=%s AND activo=1",
                (company,),
            )
        }
        if selected - valid:
            raise Error("Seleccione sectores activos de su empresa.")
        c.execute("DELETE FROM reintegro_sectores WHERE empresa_id=%s", (company,))
        for sid in sorted(selected):
            c.execute(
                "INSERT INTO reintegro_sectores(empresa_id,sector_id) VALUES(%s,%s)",
                (company, sid),
            )
        c.execute(
            "UPDATE reintegro_config SET revision=revision+1 WHERE empresa_id=%s",
            (company,),
        )
        audit(c, company, "sectores", dict(sectores=sorted(selected)), user=user)


def configuration(employee):
    today = now_local().date()
    this = today.replace(day=1)
    previous = (this - timedelta(days=1)).replace(day=1)
    with db.transaction(read_only=True) as c:
        allowed = enabled(c, employee)
        reopened = db.all_rows(
            c,
            "SELECT id,periodo,reabierto_hasta FROM reintegro_solicitudes WHERE empresa_id=%s AND empleado_id=%s AND reabierto_hasta>=%s AND estado IN ('borrador','devuelta')",
            (employee["empresa_id"], employee["id"], today),
        )
    return dict(
        habilitado=allowed,
        fecha_actual=today,
        periodos_habilitados=[
            m.strftime("%Y-%m")
            for m in (previous, this)
            if allowed and today <= deadline(m)
        ],
        reaperturas=reopened,
        fecha_cierre_dia=15,
        kilometros_informativos=True,
        foto_odometro_obligatoria=False,
    )


def report(actor, value):
    month = period(value)
    where = "e.empresa_id=%s"
    args = [month, actor["empresa_id"]]
    if not actor.get("global"):
        where += " AND e.reporta_a_empleado_id=%s AND e.id<>%s"
        args.extend([actor.get("empleado_id") or 0] * 2)
    with db.transaction(read_only=True) as c:
        rows = db.all_rows(
            c,
            """SELECT e.id empleado_id,e.legajo,CONCAT_WS(' ',e.apellido,e.nombre) empleado_nombre,
            s.nombre sector_nombre,r.id,r.kilometros,r.estado,r.total_solicitado,r.total_aprobado,r.reabierto_hasta
            FROM empleados e LEFT JOIN sectores s ON s.id=e.sector_id AND s.empresa_id=e.empresa_id
            LEFT JOIN reintegro_solicitudes r ON r.empleado_id=e.id AND r.empresa_id=e.empresa_id AND r.periodo=%s
            WHERE """
            + where
            + """ AND (r.id IS NOT NULL OR (e.activo=1 AND s.activo=1 AND EXISTS(SELECT 1 FROM reintegro_sectores h WHERE h.empresa_id=e.empresa_id AND h.sector_id=e.sector_id)))
            ORDER BY e.apellido,e.nombre,e.id LIMIT 10001""",
            tuple(args),
        )
    if len(rows) > 10000:
        raise Error("El informe supera 10.000 empleados. Acote el alcance.", 400)
    return dict(periodo=month, items=rows)


def generate_reminders():
    """In-app delivery on day 5; unique key makes multiple workers safe."""
    now = now_local()
    if now.day != 5:
        return 0
    month = (now.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    message = f"Recordá completar tus viáticos de {month:%m/%Y}. Podés enviarlos hasta el 15/{now:%m/%Y}."
    with db.transaction() as c:
        c.execute(
            """INSERT IGNORE INTO reintegro_recordatorios(empresa_id,empleado_id,periodo,mensaje,creado_at)
            SELECT e.empresa_id,e.id,%s,%s,%s FROM empleados e
            JOIN reintegro_sectores h ON h.empresa_id=e.empresa_id AND h.sector_id=e.sector_id
            JOIN sectores s ON s.id=h.sector_id AND s.empresa_id=e.empresa_id AND s.activo=1
            LEFT JOIN reintegro_solicitudes r ON r.empresa_id=e.empresa_id AND r.empleado_id=e.id AND r.periodo=%s
            WHERE e.activo=1 AND (r.id IS NULL OR r.estado IN ('borrador','devuelta'))""",
            (month, message, now, month),
        )
        return c.rowcount


def reminders(employee):
    with db.transaction(read_only=True) as c:
        return db.all_rows(
            c,
            """SELECT id,periodo,mensaje,creado_at FROM reintegro_recordatorios
            WHERE empresa_id=%s AND empleado_id=%s AND leido_at IS NULL ORDER BY id DESC LIMIT 30""",
            (employee["empresa_id"], employee["id"]),
        )


def read_reminder(employee, rid):
    with db.transaction() as c:
        if not db.one(
            c,
            "SELECT id FROM reintegro_recordatorios WHERE id=%s AND empresa_id=%s AND empleado_id=%s",
            (rid, employee["empresa_id"], employee["id"]),
        ):
            raise Error("Recordatorio no encontrado.", 404)
        c.execute(
            "UPDATE reintegro_recordatorios SET leido_at=COALESCE(leido_at,%s) WHERE id=%s",
            (now_local(), rid),
        )

"""EPP: tenant-scoped catalog, employee sizes, locked approvals and partial deliveries."""

import hashlib
import json
from uuid import UUID
from repositories import carga_repository as db
from services.carga_service import (
    CargaError as Error,
    now_local,
    text_field,
    positive_int,
    date_field,
    prepare_photos,
)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def decode(row):
    for key in ("talles", "sectores", "puestos"):
        if key in row and isinstance(row[key], str):
            row[key] = json.loads(row[key])
    return row


def integer(value, name, maximum=1000, zero=False):
    result = int(str(value)) if str(value).isdigit() else -1
    if result < (0 if zero else 1) or result > maximum:
        raise Error(f"{name}: use un entero entre {0 if zero else 1} y {maximum}.")
    return result


def key(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        raise Error("envio_id debe ser UUID válido.")


def audit(c, who, action, data, pid=None):
    db.insert(
        c,
        "epp_auditoria",
        dict(
            empresa_id=who["empresa_id"],
            pedido_id=pid,
            empleado_id=who.get("empleado_id"),
            usuario_id=who.get("user_id"),
            accion=action,
            datos=dumps(data),
            creado_at=now_local(),
        ),
    )


def employee(c, who, eid, lock=False):
    row = db.one(
        c,
        "SELECT * FROM empleados WHERE id=%s AND empresa_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (eid, who["empresa_id"]),
    )
    if not row:
        raise Error("Empleado no encontrado.", 404)
    if who.get("mode") == "empleado":
        allowed = row["id"] == who["empleado_id"]
    else:
        allowed = (
            who.get("global")
            or row.get("reporta_a_empleado_id") == who.get("empleado_id")
            and who.get("empleado_id") is not None
        )
    if not allowed:
        raise Error("Sin acceso a este empleado.", 403)
    return row


def available(article, emp):
    return (
        article["activo"]
        and (not article["sectores"] or emp["sector_id"] in article["sectores"])
        and (not article["puestos"] or emp["puesto_id"] in article["puestos"])
    )


def catalogs(who, eid=None):
    with db.transaction(read_only=True) as c:
        emp = employee(c, who, eid) if eid else None
        rows = [
            decode(r)
            for r in db.all_rows(
                c,
                "SELECT id,nombre,categoria,descripcion,activo,talles,sectores,puestos,aviso_anual,(imagen IS NOT NULL) tiene_imagen FROM epp_articulos WHERE empresa_id=%s ORDER BY nombre",
                (who["empresa_id"],),
            )
        ]
        return [r for r in rows if not emp or available(r, emp)]


def save_article(who, data, photo=None):
    if not who.get("global"):
        raise Error("Solo responsables de EPP pueden administrar el catálogo.", 403)
    sizes = data.get("talles", [])
    if (
        not isinstance(sizes, list)
        or not 1 <= len(sizes) <= 100
        or any(not isinstance(s, str) or not s.strip() or len(s) > 80 for s in sizes)
    ):
        raise Error("Defina entre 1 y 100 talles, medidas o Talle único.")
    values = dict(
        nombre=text_field(data, "nombre", 120),
        categoria=text_field(data, "categoria", 80),
        descripcion=text_field(data, "descripcion", 1000, False),
        talles=dumps(list(dict.fromkeys(s.strip() for s in sizes))),
        activo=integer(data.get("activo", 1), "Activo", 1, True),
        aviso_anual=integer(data.get("aviso_anual", 0), "Aviso anual", 1000, True),
        actualizado_at=now_local(),
    )
    if photo:
        values["imagen"] = prepare_photos([photo])[0]["contenido"]
    with db.transaction() as c:
        if not db.one(
            c,
            "SELECT id FROM epp_categorias WHERE empresa_id=%s AND nombre=%s AND activo=1",
            (who["empresa_id"], values["categoria"]),
        ):
            raise Error("Seleccione una categoría activa.")
        for field, table in [("sectores", "sectores"), ("puestos", "puestos")]:
            ids = data.get(field, [])
            if not isinstance(ids, list) or len(ids) > 500:
                raise Error("Selección de sectores/puestos inválida.")
            ids = list(dict.fromkeys(positive_int(i, field) for i in ids))
            for rid in ids:
                if not db.one(
                    c,
                    f"SELECT id FROM {table} WHERE id=%s AND empresa_id=%s",
                    (rid, who["empresa_id"]),
                ):
                    raise Error("Sector/puesto ajeno a la empresa.")
            values[field] = dumps(ids)
        rid = positive_int(data["id"], "Artículo") if data.get("id") else None
        if rid:
            if not db.one(
                c,
                "SELECT id FROM epp_articulos WHERE id=%s AND empresa_id=%s FOR UPDATE",
                (rid, who["empresa_id"]),
            ):
                raise Error("Artículo no encontrado.", 404)
            c.execute(
                "UPDATE epp_articulos SET "
                + ",".join(f"{k}=%s" for k in values)
                + " WHERE id=%s",
                (*values.values(), rid),
            )
        else:
            rid = db.insert(
                c, "epp_articulos", dict(empresa_id=who["empresa_id"], **values)
            )
        audit(c, who, "articulo", {k: v for k, v in values.items() if k != "imagen"})
    return rid


def sizes(who, eid):
    with db.transaction(read_only=True) as c:
        employee(c, who, eid)
        return db.all_rows(
            c,
            "SELECT t.*,a.nombre FROM epp_talles t JOIN epp_articulos a ON a.id=t.articulo_id WHERE t.empresa_id=%s AND t.empleado_id=%s ORDER BY a.nombre",
            (who["empresa_id"], eid),
        )


def save_size(who, eid, data):
    aid = positive_int(data.get("articulo_id"), "Artículo")
    with db.transaction() as c:
        emp = employee(c, who, eid)
        if not emp["activo"]:
            raise Error("Empleado inactivo.")
        article = db.one(
            c,
            "SELECT * FROM epp_articulos WHERE id=%s AND empresa_id=%s FOR UPDATE",
            (aid, who["empresa_id"]),
        )
        if not article or not available(decode(article), emp):
            raise Error("Artículo no habilitado para este empleado.")
        previous = db.one(
            c,
            "SELECT talle,medidas FROM epp_talles WHERE empresa_id=%s AND empleado_id=%s AND articulo_id=%s",
            (who["empresa_id"], eid, aid),
        )
        if data.get("eliminar") is True:
            c.execute(
                "DELETE FROM epp_talles WHERE empresa_id=%s AND empleado_id=%s AND articulo_id=%s",
                (who["empresa_id"], eid, aid),
            )
        else:
            if data.get("talle") not in article["talles"]:
                raise Error("Seleccione un talle vigente.")
            c.execute(
                "INSERT INTO epp_talles(empresa_id,empleado_id,articulo_id,talle,medidas,actualizado_at) VALUES(%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE talle=VALUES(talle),medidas=VALUES(medidas),actualizado_at=VALUES(actualizado_at)",
                (
                    who["empresa_id"],
                    eid,
                    aid,
                    data["talle"],
                    text_field(data, "medidas", 300, False),
                    now_local(),
                ),
            )
        audit(
            c,
            who,
            "talle",
            dict(empleado_id=eid, articulo_id=aid, anterior=previous, nuevo=dict(data)),
        )


def total_year(c, company, eid, aid, year):
    return db.one(
        c,
        """SELECT COALESCE(SUM(el.cantidad),0) total FROM epp_entregas e
        JOIN epp_entrega_lineas el ON el.entrega_id=e.id JOIN epp_lineas l ON l.id=el.linea_id
        JOIN epp_pedidos p ON p.id=e.pedido_id WHERE p.empresa_id=%s AND p.empleado_id=%s
        AND l.articulo_id=%s AND e.anulada=0 AND e.fecha >= %s AND e.fecha < %s""",
        (company, eid, aid, f"{year}-01-01", f"{year+1}-01-01"),
    )["total"]


def create(who, eid, data):
    token = key(data.get("envio_id"))
    if data.get("accion", "enviar") not in ("enviar", "borrador"):
        raise Error("Acción de alta inválida.")
    digest = hashlib.sha256(dumps(data).encode()).hexdigest()
    lines = data.get("items")
    if (
        not isinstance(lines, list)
        or not 1 <= len(lines) <= 50
        or any(not isinstance(i, dict) for i in lines)
    ):
        raise Error("Incluya entre 1 y 50 artículos.")
    with db.transaction() as c:
        emp = employee(c, who, eid, True)
        # Serialize employee writes, including concurrent retries with the same UUID.
        c.execute("SELECT id FROM empleados WHERE id=%s FOR UPDATE", (eid,))
        c.fetchone()
        old = db.one(
            c,
            "SELECT id,envio_hash FROM epp_pedidos WHERE empresa_id=%s AND empleado_id=%s AND envio_id=%s",
            (who["empresa_id"], eid, token),
        )
        if old:
            if old["envio_hash"] != digest:
                raise Error("UUID reutilizado con datos diferentes.", 409)
            return old["id"], False
        if not emp["activo"] or not emp["sucursal_id"]:
            raise Error("Empleado sin sucursal o inactivo.")
        prepared = []
        if len({str(i.get("articulo_id")) for i in lines}) != len(lines):
            raise Error("Use una sola línea por artículo y sume las cantidades.")
        for item in lines:
            article = db.one(
                c,
                "SELECT * FROM epp_articulos WHERE id=%s AND empresa_id=%s",
                (positive_int(item.get("articulo_id"), "Artículo"), who["empresa_id"]),
            )
            if not article or not available(decode(article), emp):
                raise Error("Artículo no habilitado para sector/puesto.")
            if item.get("talle") not in article["talles"]:
                raise Error("Talle no disponible.")
            prepared.append(
                dict(
                    articulo_id=article["id"],
                    nombre=article["nombre"],
                    categoria=article["categoria"],
                    talle=item["talle"],
                    medidas=text_field(item, "medidas", 300, False),
                    cantidad=integer(item.get("cantidad"), "Cantidad"),
                )
            )
        pid = db.insert(
            c,
            "epp_pedidos",
            dict(
                empresa_id=who["empresa_id"],
                empleado_id=eid,
                sucursal_id=emp["sucursal_id"],
                empleado_nombre=f"{emp['apellido']} {emp['nombre']}",
                legajo=str(emp["legajo"]),
                estado="borrador" if data.get("accion") == "borrador" else "pendiente",
                motivo=text_field(data, "motivo", 1000),
                envio_id=token,
                envio_hash=digest,
                creado_at=now_local(),
            ),
        )
        for line in prepared:
            db.insert(c, "epp_lineas", dict(pedido_id=pid, **line))
        audit(c, who, "crear", data, pid)
    return pid, True


def get(c, who, pid, lock=False):
    row = db.one(
        c,
        "SELECT * FROM epp_pedidos WHERE id=%s AND empresa_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (pid, who["empresa_id"]),
    )
    if not row:
        raise Error("Pedido no encontrado.", 404)
    employee(c, who, row["empleado_id"], lock)
    row.pop("envio_hash")
    row.pop("envio_id")
    row["items"] = db.all_rows(
        c,
        """SELECT l.*,COALESCE((SELECT SUM(el.cantidad) FROM epp_entrega_lineas el
        JOIN epp_entregas e ON e.id=el.entrega_id WHERE el.linea_id=l.id AND e.anulada=0),0) entregada
        FROM epp_lineas l WHERE l.pedido_id=%s ORDER BY l.id""",
        (pid,),
    )
    for line in row["items"]:
        line["entregada"] = int(line["entregada"])
    return row


def detail(who, pid):
    with db.transaction(read_only=True) as c:
        row = get(c, who, pid)
        row["entregas"] = db.all_rows(
            c,
            "SELECT id,fecha,responsable_id,observaciones,anulada,(firma IS NOT NULL) firmada FROM epp_entregas WHERE pedido_id=%s ORDER BY id DESC",
            (pid,),
        )
        row["historial"] = db.all_rows(
            c,
            "SELECT accion,datos,creado_at,usuario_id FROM epp_auditoria WHERE empresa_id=%s AND pedido_id=%s ORDER BY id",
            (who["empresa_id"], pid),
        )
        for item in row["items"]:
            item["entregado_anio"] = int(
                total_year(
                    c,
                    who["empresa_id"],
                    row["empleado_id"],
                    item["articulo_id"],
                    now_local().year,
                )
            )
            cat = db.one(
                c,
                "SELECT aviso_anual FROM epp_articulos WHERE id=%s",
                (item["articulo_id"],),
            )
            item["aviso_anual"] = cat["aviso_anual"]
    return row


def history(who, filters):
    page = integer(filters.get("page", 1), "Página", 100000)
    where = ["p.empresa_id=%s"]
    args = [who["empresa_id"]]
    if who.get("mode") == "empleado":
        where.append("p.empleado_id=%s")
        args.append(who["empleado_id"])
    elif not who.get("global"):
        where.append("emp.reporta_a_empleado_id=%s")
        args.append(who.get("empleado_id") or -1)
    for field in ("empleado_id", "sucursal_id"):
        if filters.get(field):
            where.append("p." + field + "=%s")
            args.append(positive_int(filters[field], field))
    if filters.get("estado"):
        where.append("p.estado=%s")
        args.append(filters["estado"])
    clause = " AND ".join(where)
    with db.transaction(read_only=True) as c:
        base = (
            " FROM epp_pedidos p JOIN empleados emp ON emp.id=p.empleado_id WHERE "
            + clause
        )
        total = db.one(c, "SELECT COUNT(*) total" + base, args)["total"]
        rows = db.all_rows(
            c,
            "SELECT p.id,p.empleado_nombre,p.legajo,p.sucursal_id,p.estado,p.revision,p.creado_at"
            + base
            + " ORDER BY p.id DESC LIMIT 30 OFFSET %s",
            (*args, (page - 1) * 30),
        )
    return dict(items=rows, total=total, page=page, per_page=30)


def action(who, pid, data):
    with db.transaction() as c:
        row = get(c, who, pid, True)
        if positive_int(data.get("revision"), "Revisión") != row["revision"]:
            raise Error("El pedido cambió. Actualice antes de continuar.", 409)
        action = data.get("accion")
        reason = text_field(data, "motivo", 1000, False)
        if action == "cancelar":
            if row["estado"] not in ("borrador", "pendiente"):
                raise Error("Solo se cancelan borradores o pedidos pendientes.", 409)
            if not reason:
                raise Error("Indique el motivo de cancelación.")
            state = "cancelado"
        elif action == "resolver":
            if who.get("mode") == "empleado" or not who.get("approve"):
                raise Error("No puede aprobar.", 403)
            if who.get("empleado_id") == row["empleado_id"]:
                raise Error("No puede aprobar su propio pedido.", 403)
            if row["estado"] != "pendiente":
                raise Error("El pedido ya fue resuelto.", 409)
            values = data.get("cantidades", {})
            if not isinstance(values, dict) or set(values) != set(
                str(i["id"]) for i in row["items"]
            ):
                raise Error("Resuelva todas las líneas.")
            approved = 0
            for line in row["items"]:
                n = integer(
                    values[str(line["id"])], "Cantidad aprobada", line["cantidad"], True
                )
                if n < line["cantidad"] and not reason:
                    raise Error("Justifique la aprobación parcial o el rechazo.")
                c.execute(
                    "UPDATE epp_lineas SET aprobada=%s,motivo=%s WHERE id=%s",
                    (n, reason, line["id"]),
                )
                approved += n
            state = "aprobado" if approved else "rechazado"
        else:
            raise Error("Acción no válida.")
        c.execute(
            "UPDATE epp_pedidos SET estado=%s,revision=revision+1 WHERE id=%s",
            (state, pid),
        )
        audit(c, who, action, data, pid)


def deliver(who, pid, data):
    if not who.get("global") or not who.get("deliver"):
        raise Error("Solo responsables autorizados registran entregas.", 403)
    token = key(data.get("envio_id"))
    date = date_field(data.get("fecha"))
    if date > now_local().date():
        raise Error("La entrega no puede ser futura.")
    with db.transaction() as c:
        row = get(c, who, pid, True)
        old = db.one(
            c,
            "SELECT id,envio_hash FROM epp_entregas WHERE pedido_id=%s AND clave=%s",
            (pid, token),
        )
        if old:
            if old["envio_hash"] != hashlib.sha256(dumps(data).encode()).hexdigest():
                raise Error("UUID de entrega reutilizado con otro contenido.", 409)
            return old["id"], False
        c.execute(
            "SELECT id FROM empleados WHERE id=%s FOR UPDATE", (row["empleado_id"],)
        )
        c.fetchone()
        if positive_int(data.get("revision"), "Revisión") != row["revision"]:
            raise Error("Actualice la revisión.", 409)
        if row["estado"] not in ("aprobado", "parcial"):
            raise Error("El pedido no está aprobado o ya se entregó.", 409)
        if date < row["creado_at"].date():
            raise Error("La entrega no puede ser anterior al pedido.")
        values = data.get("cantidades", {})
        if not isinstance(values, dict) or set(values) - set(
            str(i["id"]) for i in row["items"]
        ):
            raise Error("Líneas no válidas.")
        prepared = []
        remaining = 0
        note = text_field(data, "observaciones", 1000, False)
        for line in row["items"]:
            left = line["aprobada"] - int(line["entregada"])
            n = integer(
                values.get(str(line["id"]), 0), "Cantidad entregada", left, True
            )
            remaining += left - n
            if n:
                article = db.one(
                    c,
                    "SELECT aviso_anual FROM epp_articulos WHERE id=%s",
                    (line["articulo_id"],),
                )
                total = total_year(
                    c,
                    who["empresa_id"],
                    row["empleado_id"],
                    line["articulo_id"],
                    date.year,
                )
                same = sum(
                    q for l, q in prepared if l["articulo_id"] == line["articulo_id"]
                )
                if (
                    article["aviso_anual"]
                    and total + same + n > article["aviso_anual"]
                    and not note
                ):
                    raise Error(
                        "Se supera la cantidad anual orientativa. Justifique la excepción en observaciones."
                    )
                prepared.append((line, n))
        if not prepared:
            raise Error("Indique al menos una unidad a entregar.")
        did = db.insert(
            c,
            "epp_entregas",
            dict(
                pedido_id=pid,
                fecha=date,
                responsable_id=who["user_id"],
                observaciones=note,
                clave=token,
                envio_hash=hashlib.sha256(dumps(data).encode()).hexdigest(),
                creado_at=now_local(),
            ),
        )
        for line, n in prepared:
            db.insert(
                c,
                "epp_entrega_lineas",
                dict(entrega_id=did, linea_id=line["id"], cantidad=n),
            )
        c.execute(
            "UPDATE epp_pedidos SET estado=%s,revision=revision+1 WHERE id=%s",
            ("parcial" if remaining else "entregado", pid),
        )
        audit(c, who, "entregar", dict(entrega_id=did, **data), pid)
    return did, True


def receipt(who, did):
    with db.transaction(read_only=True) as c:
        row = db.one(
            c,
            "SELECT id,pedido_id,fecha,responsable_id,observaciones,anulada,(firma IS NOT NULL) firmada FROM epp_entregas WHERE id=%s",
            (did,),
        )
        if not row:
            raise Error("Entrega no encontrada.", 404)
        row["pedido"] = get(c, who, row["pedido_id"])
        row["items"] = db.all_rows(
            c,
            "SELECT l.nombre,l.talle,l.medidas,el.cantidad FROM epp_entrega_lineas el JOIN epp_lineas l ON l.id=el.linea_id WHERE el.entrega_id=%s",
            (did,),
        )
        row["empresa"] = db.one(
            c, "SELECT * FROM empresas WHERE id=%s", (who["empresa_id"],)
        )
        row["sucursal"] = db.one(
            c,
            "SELECT nombre FROM sucursales WHERE id=%s",
            (row["pedido"]["sucursal_id"],),
        )["nombre"]
    return row


def delivery_update(who, did, data, photo=None):
    if not who.get("global") or not who.get("deliver"):
        raise Error("Sin permiso de entrega.", 403)
    content = prepare_photos([photo])[0]["contenido"] if photo else None
    with db.transaction() as c:
        entry = db.one(c, "SELECT pedido_id FROM epp_entregas WHERE id=%s", (did,))
        if not entry:
            raise Error("Entrega no encontrada.", 404)
        row = get(c, who, entry["pedido_id"], True)
        if data.get("accion") == "anular":
            reason = text_field(data, "motivo", 1000)
            c.execute("UPDATE epp_entregas SET anulada=1 WHERE id=%s", (did,))
            refreshed = get(c, who, row["id"])
            state = (
                "parcial"
                if any(i["entregada"] for i in refreshed["items"])
                else "aprobado"
            )
            c.execute(
                "UPDATE epp_pedidos SET estado=%s,revision=revision+1 WHERE id=%s",
                (state, row["id"]),
            )
            audit(c, who, "anular_entrega", dict(id=did, motivo=reason), row["id"])
        elif content:
            old = db.one(c, "SELECT firma FROM epp_entregas WHERE id=%s", (did,))
            if old["firma"]:
                raise Error(
                    "La planilla firmada ya está adjunta; no se sobrescribe.", 409
                )
            c.execute("UPDATE epp_entregas SET firma=%s WHERE id=%s", (content, did))
            audit(c, who, "planilla_firmada", dict(id=did), row["id"])
        else:
            raise Error("Adjunte una imagen de la planilla firmada.")


def image(who, kind, rid):
    if kind == "firmas":
        receipt(who, rid)
        sql = "SELECT firma contenido FROM epp_entregas WHERE id=%s"
        args = (rid,)
    else:
        sql = "SELECT imagen contenido FROM epp_articulos WHERE id=%s AND empresa_id=%s"
        args = (rid, who["empresa_id"])
    with db.transaction(read_only=True) as c:
        row = db.one(c, sql, args)
    if not row or not row["contenido"]:
        raise Error("Imagen no encontrada.", 404)
    return row


def report(who, filters):
    year = integer(filters.get("anio", now_local().year), "Año", 9998)
    if year < 2000:
        raise Error("Año no válido.")
    where = ["p.empresa_id=%s", "e.anulada=0", "e.fecha >= %s", "e.fecha < %s"]
    args = [who["empresa_id"], f"{year}-01-01", f"{year+1}-01-01"]
    if who.get("mode") == "empleado":
        where.append("p.empleado_id=%s")
        args.append(who["empleado_id"])
    elif not who.get("global"):
        where.append("emp.reporta_a_empleado_id=%s")
        args.append(who.get("empleado_id") or -1)
    for field in ("sucursal_id", "empleado_id"):
        if filters.get(field):
            where.append("p." + field + "=%s")
            args.append(positive_int(filters[field], field))
    with db.transaction(read_only=True) as c:
        rows = db.all_rows(
            c,
            """SELECT p.empleado_id,p.legajo,p.empleado_nombre,p.sucursal_id,l.articulo_id,l.nombre,l.categoria,l.talle,l.medidas,SUM(el.cantidad) cantidad
            FROM epp_entregas e JOIN epp_pedidos p ON p.id=e.pedido_id JOIN empleados emp ON emp.id=p.empleado_id
            JOIN epp_entrega_lineas el ON el.entrega_id=e.id JOIN epp_lineas l ON l.id=el.linea_id WHERE """
            + " AND ".join(where)
            + " GROUP BY p.empleado_id,p.legajo,p.empleado_nombre,p.sucursal_id,l.articulo_id,l.nombre,l.categoria,l.talle,l.medidas ORDER BY p.empleado_nombre,l.nombre LIMIT 10001",
            args,
        )
    if len(rows) > 10000:
        raise Error("Acote por sucursal o empleado: máximo 10.000 filas.")
    for line in rows:
        line["cantidad"] = int(line["cantidad"])
    return dict(anio=year, items=rows)


def edit_order(who, pid, data):
    """Pending orders can be corrected; snapshots of earlier versions remain in audit."""
    lines = data.get("items")
    if (
        not isinstance(lines, list)
        or not 1 <= len(lines) <= 50
        or any(not isinstance(i, dict) for i in lines)
    ):
        raise Error("Incluya entre 1 y 50 artículos.")
    with db.transaction() as c:
        row = get(c, who, pid, True)
        if (
            row["estado"] not in ("borrador", "pendiente")
            or positive_int(data.get("revision"), "Revisión") != row["revision"]
        ):
            raise Error(
                "Solo puede modificar la versión vigente de un pedido pendiente.", 409
            )
        emp = employee(c, who, row["empleado_id"])
        if not emp["activo"]:
            raise Error("Empleado inactivo.")
        prepared = []
        if len({str(i.get("articulo_id")) for i in lines}) != len(lines):
            raise Error("Use una sola línea por artículo y sume las cantidades.")
        for item in lines:
            article = db.one(
                c,
                "SELECT * FROM epp_articulos WHERE id=%s AND empresa_id=%s",
                (positive_int(item.get("articulo_id"), "Artículo"), who["empresa_id"]),
            )
            if not article or not available(decode(article), emp):
                raise Error("Artículo no habilitado.")
            if item.get("talle") not in article["talles"]:
                raise Error("Talle no disponible.")
            prepared.append(
                dict(
                    pedido_id=pid,
                    articulo_id=article["id"],
                    nombre=article["nombre"],
                    categoria=article["categoria"],
                    talle=item["talle"],
                    medidas=text_field(item, "medidas", 300, False),
                    cantidad=integer(item.get("cantidad"), "Cantidad"),
                )
            )
        reason = text_field(data, "motivo", 1000)
        audit(c, who, "editar_pedido", dict(anterior=row, nuevo=data), pid)
        c.execute("DELETE FROM epp_lineas WHERE pedido_id=%s", (pid,))
        for line in prepared:
            db.insert(c, "epp_lineas", line)
        state = "borrador" if data.get("accion") == "borrador" else "pendiente"
        c.execute(
            "UPDATE epp_pedidos SET motivo=%s,estado=%s,revision=revision+1 WHERE id=%s",
            (reason, state, pid),
        )


def categories(who):
    with db.transaction(read_only=True) as c:
        return db.all_rows(
            c,
            "SELECT id,nombre,activo FROM epp_categorias WHERE empresa_id=%s ORDER BY nombre",
            (who["empresa_id"],),
        )


def save_category(who, data):
    if not who.get("global"):
        raise Error("Solo responsables de EPP administran categorías.", 403)
    name = text_field(data, "nombre", 80)
    active = integer(data.get("activo", 1), "Activo", 1, True)
    with db.transaction() as c:
        if data.get("id"):
            rid = positive_int(data["id"], "Categoría")
            old = db.one(
                c,
                "SELECT nombre FROM epp_categorias WHERE id=%s AND empresa_id=%s FOR UPDATE",
                (rid, who["empresa_id"]),
            )
            if not old:
                raise Error("Categoría no encontrada.", 404)
            c.execute(
                "UPDATE epp_categorias SET nombre=%s,activo=%s WHERE id=%s",
                (name, active, rid),
            )
            c.execute(
                "UPDATE epp_articulos SET categoria=%s WHERE empresa_id=%s AND categoria=%s",
                (name, who["empresa_id"], old["nombre"]),
            )
        else:
            rid = db.insert(
                c,
                "epp_categorias",
                dict(empresa_id=who["empresa_id"], nombre=name, activo=active),
            )
        audit(c, who, "categoria", dict(id=rid, nombre=name, activo=active))
    return rid

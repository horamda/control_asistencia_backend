"""ARS reimbursement requests with private receipts and single-review workflow."""

import hashlib
import json
import re
from decimal import Decimal
from datetime import timedelta
from uuid import UUID
from repositories import carga_repository as db
from services import reintegro_monthly_service as monthly
from services.carga_service import (
    CargaError as Error,
    prepare_photos,
    now_local,
    positive_int,
    text_field,
    date_field,
)

STATES = (
    "borrador",
    "pendiente",
    "devuelta",
    "aprobada",
    "rechazada",
    "pagada",
    "cancelada",
)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def audit(c, company, action, data, rid=None, user=None, employee=None):
    db.insert(
        c,
        "reintegro_auditoria",
        dict(
            empresa_id=company,
            solicitud_id=rid,
            usuario_id=user,
            empleado_id=employee,
            accion=action,
            datos=dumps(data),
            creado_at=now_local(),
        ),
    )


def amount(value):
    # Decimal strings: no floats, scientific notation, thousands separators or rounding.
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", value):
        raise Error('Importe inválido. Envíe pesos como texto, por ejemplo "1250.50".')
    result = Decimal(value)
    if result <= 0:
        raise Error("El importe debe ser mayor que cero.")
    return result.quantize(Decimal(".01"))


def categories(company):
    with db.transaction(read_only=True) as c:
        return db.all_rows(
            c,
            "SELECT id,nombre,activo FROM reintegro_categorias WHERE empresa_id=%s ORDER BY nombre",
            (company,),
        )


def save_category(company, user, data):
    name = text_field(data, "nombre", 120)
    active = str(data.get("activo", "1"))
    if active not in ("0", "1"):
        raise Error("Estado inválido.")
    with db.transaction() as c:
        rid = positive_int(data["id"], "Categoría") if data.get("id") else None
        if rid:
            if not db.one(
                c,
                "SELECT id FROM reintegro_categorias WHERE id=%s AND empresa_id=%s FOR UPDATE",
                (rid, company),
            ):
                raise Error("Categoría no encontrada.", 404)
            c.execute(
                "UPDATE reintegro_categorias SET nombre=%s,activo=%s WHERE id=%s",
                (name, int(active), rid),
            )
        else:
            rid = db.insert(
                c,
                "reintegro_categorias",
                dict(empresa_id=company, nombre=name, activo=int(active)),
            )
        audit(
            c, company, "categoria", dict(id=rid, nombre=name, activo=active), user=user
        )


def parse(data, files, *, allow_existing=False, month=None):
    action = data.get("accion", "enviar")
    if action not in ("borrador", "enviar"):
        raise Error("Acción inválida.")
    complete = action == "enviar"
    items = data.get("gastos")
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            raise Error("Gastos debe ser una lista JSON.")
    if not isinstance(items, list) or not 0 <= len(items) <= 50:
        raise Error("Máximo 50 gastos por período; puede informar solo kilómetros.")
    result = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise Error("Gasto inválido.")
        day = date_field(item.get("fecha")) if complete or item.get("fecha") else None
        if day and (day > now_local().date() or day.year < 2000):
            raise Error(
                "La fecha del gasto no puede ser futura ni anterior al año 2000."
            )
        if day and month and day.replace(day=1) != month:
            raise Error("La fecha de cada gasto debe pertenecer al período.")
        if month and complete and not item.get("categoria_id"):
            raise Error("Seleccione un concepto del catálogo para cada gasto.")
        photos = files.getlist("fotos_" + str(i))
        existing = item.get("fotos_existentes", []) if allow_existing else []
        if not isinstance(existing, list):
            raise Error("Comprobantes existentes inválidos.")
        existing = [positive_int(fid, "Comprobante") for fid in existing]
        if len(set(existing)) != len(existing):
            raise Error("No repita un comprobante.")
        if len(photos) + len(existing) > 3:
            raise Error("Máximo tres fotos por gasto.")
        result.append(
            dict(
                fecha=day,
                concepto=text_field(item, "concepto", 500, complete),
                importe=(
                    amount(item.get("importe"))
                    if complete or item.get("importe") not in (None, "")
                    else None
                ),
                numero_comprobante=text_field(item, "numero_comprobante", 100, False),
                emisor=text_field(item, "emisor", 180, False),
                categoria_id=(
                    positive_int(item["categoria_id"], "Categoría")
                    if item.get("categoria_id")
                    else None
                ),
                fotos=prepare_photos(photos),
                **({"fotos_existentes": existing} if allow_existing else {}),
            )
        )
    if any(
        key not in {"odometro", *("fotos_" + str(i) for i in range(len(items)))}
        for key in files
    ):
        raise Error("Hay fotos sin un gasto asociado.")
    action = data.get("accion", "enviar")
    if action not in ("borrador", "enviar"):
        raise Error("Acción inválida.")
    if action == "enviar" and any(
        not r["fotos"] and not r.get("fotos_existentes") for r in result
    ):
        raise Error("Cada gasto debe tener al menos una foto del comprobante.")
    if sum(len(f["contenido"]) for r in result for f in r["fotos"]) > 20 * 1024 * 1024:
        raise Error("Los comprobantes procesados superan 20 MB.", 413)
    return result, action, text_field(data, "observaciones", 2000, False)


def store(employee, data, files, rid=None, *, web_actor=None):
    month = (
        monthly.period(data.get("periodo"))
        if rid is None or data.get("periodo")
        else None
    )
    km = data.get("kilometros")
    if km in (None, ""):
        km = None
    elif (
        isinstance(km, bool)
        or not str(km).isascii()
        or not str(km).isdigit()
        or int(km) > 1000000
    ):
        raise Error(
            "Kilómetros: ingrese un entero de 0 a 1.000.000, o deje vacío si no corresponde."
        )
    else:
        km = int(km)
    odometer_files = files.getlist("odometro")
    if len(odometer_files) > 1:
        raise Error("Adjunte una sola foto del odómetro.")
    odometer = prepare_photos(odometer_files)
    remove_odometer = str(data.get("quitar_odometro", "0"))
    if remove_odometer not in ("0", "1"):
        raise Error("quitar_odometro debe ser 0 o 1.")
    if web_actor is not None:
        permission = "manage_edit" if rid is not None else "manage_create"
        if (
            web_actor.get("mode") != "web"
            or not web_actor.get(permission)
            or web_actor["empresa_id"] != employee["empresa_id"]
        ):
            raise Error("No tiene permiso para administrar esta solicitud.", 403)
    items, action, notes = parse(data, files, allow_existing=True, month=month)
    try:
        key = str(UUID(str(data.get("envio_id"))))
    except (ValueError, TypeError):
        raise Error("envio_id debe ser un UUID.")
    fingerprint = hashlib.sha256(
        dumps(
            dict(
                items=[
                    {**r, "fotos": [f["sha256"] for f in r["fotos"]]} for r in items
                ],
                accion=action,
                observaciones=notes,
                periodo=month,
                kilometros=km,
                odometro=[p["sha256"] for p in odometer],
                quitar_odometro=remove_odometer,
            )
        ).encode()
    ).hexdigest()
    company = employee["empresa_id"]
    eid = employee["id"]
    with db.transaction() as c:
        owner = db.one(
            c,
            "SELECT * FROM empleados WHERE id=%s AND empresa_id=%s AND activo=1 FOR UPDATE",
            (eid, company),
        )
        if not owner:
            raise Error("Empleado no disponible.", 403)
        if (
            web_actor is not None
            and not web_actor.get("global")
            and (
                not web_actor.get("empleado_id")
                or owner.get("reporta_a_empleado_id") != web_actor["empleado_id"]
                or eid == web_actor["empleado_id"]
            )
        ):
            raise Error("El empleado no está dentro de su equipo autorizado.", 403)
        if rid is None:
            old = db.one(
                c,
                "SELECT id,contenido_hash FROM reintegro_solicitudes WHERE empresa_id=%s AND empleado_id=%s AND envio_id=%s",
                (company, eid, key),
            )
            if old:
                if old["contenido_hash"] != fingerprint:
                    raise Error(
                        "Este envio_id ya fue utilizado con otro contenido.", 409
                    )
                return old["id"], False
            if not monthly.enabled(c, owner):
                raise Error(
                    "El sector del empleado no está habilitado para viáticos.", 403
                )
            if web_actor is None:
                monthly.employee_write(c, owner, month)
            duplicate = db.one(
                c,
                "SELECT id FROM reintegro_solicitudes WHERE empresa_id=%s AND empleado_id=%s AND periodo=%s",
                (company, eid, month),
            )
            if duplicate:
                raise Error(
                    f"Ya existe una rendición para este período (#{duplicate['id']}). Abra el período existente.",
                    409,
                )
            revision = 1
        else:
            old = db.one(
                c,
                "SELECT * FROM reintegro_solicitudes WHERE id=%s AND empresa_id=%s AND empleado_id=%s FOR UPDATE",
                (rid, company, eid),
            )
            if not old:
                raise Error("Solicitud no encontrada.", 404)
            if month != old.get("periodo"):
                raise Error("El período de una rendición no puede cambiarse.", 409)
            if web_actor is None:
                monthly.employee_write(c, owner, month, old)
            editable = (
                ("borrador", "pendiente", "devuelta")
                if web_actor is not None
                else ("borrador", "devuelta")
            )
            if old["estado"] not in editable or old["revision"] != positive_int(
                data.get("revision"), "Revisión"
            ):
                raise Error("La solicitud cambió o no se puede editar.", 409)
            revision = old["revision"] + 1
        retained = set()
        for item in items:
            for fid in item.pop("fotos_existentes", []):
                if rid is None or fid in retained:
                    raise Error("Comprobante existente inválido.")
                saved = db.one(
                    c,
                    "SELECT f.contenido,f.sha256 FROM reintegro_fotos f JOIN reintegro_gastos g ON g.id=f.gasto_id WHERE f.id=%s AND g.solicitud_id=%s AND g.activo=1",
                    (fid, rid),
                )
                if not saved:
                    raise Error(
                        "El comprobante no pertenece a esta versión de la solicitud.",
                        400,
                    )
                retained.add(fid)
                item["fotos"].append(saved)
        if (
            sum(len(f["contenido"]) for item in items for f in item["fotos"])
            + sum(len(f["contenido"]) for f in odometer)
            > 20 * 1024 * 1024
        ):
            raise Error("Los comprobantes procesados superan 20 MB.", 413)
        for item in items:
            cat = (
                db.one(
                    c,
                    "SELECT nombre FROM reintegro_categorias WHERE id=%s AND empresa_id=%s AND activo=1",
                    (item["categoria_id"], company),
                )
                if item["categoria_id"]
                else None
            )
            if item["categoria_id"] and not cat:
                raise Error("Categoría no disponible para esta empresa.")
            item["categoria_nombre"] = cat["nombre"] if cat else None
        values = dict(
            estado="pendiente" if action == "enviar" else "borrador",
            revision=revision,
            total_solicitado=sum(
                (r["importe"] or Decimal("0.00") for r in items), Decimal("0.00")
            ),
            total_aprobado=Decimal("0.00"),
            observaciones=notes,
            actualizado_at=now_local(),
            sucursal_id=owner.get("sucursal_id"),
            jefe_id=owner.get("reporta_a_empleado_id"),
            periodo=month,
            kilometros=km,
        )
        if action == "enviar":
            values["reabierto_hasta"] = None
        if rid is None:
            rid = db.insert(
                c,
                "reintegro_solicitudes",
                dict(
                    empresa_id=company,
                    empleado_id=eid,
                    envio_id=key,
                    contenido_hash=fingerprint,
                    creado_at=now_local(),
                    **values,
                ),
            )
        else:
            c.execute(
                "UPDATE reintegro_solicitudes SET "
                + ",".join(k + "=%s" for k in values)
                + ",motivo=NULL,revisor_id=NULL,revisado_at=NULL WHERE id=%s",
                (*values.values(), rid),
            )
            c.execute(
                "UPDATE reintegro_gastos SET activo=0 WHERE solicitud_id=%s", (rid,)
            )
        for item in items:
            photos = item.pop("fotos")
            gid = db.insert(
                c,
                "reintegro_gastos",
                dict(solicitud_id=rid, revision_carga=revision, **item),
            )
            for photo in photos:
                db.insert(c, "reintegro_fotos", dict(gasto_id=gid, **photo))
        if odometer or remove_odometer == "1":
            c.execute(
                "UPDATE reintegro_odometros SET activo=0 WHERE solicitud_id=%s", (rid,)
            )
            for photo in odometer:
                db.insert(
                    c,
                    "reintegro_odometros",
                    dict(solicitud_id=rid, revision_carga=revision, **photo),
                )
        audit(
            c,
            company,
            (
                ("editar_admin" if old and web_actor is not None else "crear_admin")
                if web_actor is not None
                else ("enviar" if action == "enviar" else "borrador")
            ),
            dict(
                revision=revision,
                total=values["total_solicitado"],
                empleado_destino=eid,
                periodo=month,
                kilometros=km,
            ),
            rid,
            user=web_actor["user_id"] if web_actor is not None else None,
            employee=eid,
        )
    return rid, True


def scope(actor, alias="r"):
    conditions = [f"{alias}.empresa_id=%s"]
    args = [actor["empresa_id"]]
    if actor.get("mode") == "empleado":
        conditions.append(f"{alias}.empleado_id=%s")
        args.append(actor["empleado_id"])
    elif not actor.get("global"):
        conditions.append(
            f"EXISTS(SELECT 1 FROM empleados jefe_scope WHERE jefe_scope.id={alias}.empleado_id AND jefe_scope.empresa_id={alias}.empresa_id AND jefe_scope.reporta_a_empleado_id=%s) AND {alias}.empleado_id<>%s AND ({alias}.estado<>'borrador' OR {alias}.periodo IS NOT NULL)"
        )
        args.extend([actor.get("empleado_id") or 0, actor.get("empleado_id") or 0])
    else:
        conditions.append(
            f"({alias}.estado<>'borrador' OR {alias}.periodo IS NOT NULL)"
        )
    return " AND ".join(conditions), args


def history(actor, filters, *, per_page=30):
    where, args = scope(actor)
    if filters.get("periodo"):
        where += " AND r.periodo=%s"
        args.append(monthly.period(filters["periodo"]))
    if filters.get("estado"):
        if filters["estado"] not in STATES:
            raise Error("Estado inválido.")
        where += " AND r.estado=%s"
        args.append(filters["estado"])
    if filters.get("desde"):
        where += " AND r.creado_at>=%s"
        args.append(date_field(filters["desde"]))
    if filters.get("hasta"):
        day = date_field(filters["hasta"])
        if day.year >= 9999:
            raise Error("Fecha hasta fuera de rango.")
        where += " AND r.creado_at<%s"
        args.append(day + timedelta(days=1))
    if (
        filters.get("desde")
        and filters.get("hasta")
        and date_field(filters["desde"]) > date_field(filters["hasta"])
    ):
        raise Error("El rango de fechas es inválido.")
    page = positive_int(filters.get("page") or 1, "Página")
    if page > 100000:
        raise Error("Página fuera de rango.")
    with db.transaction(read_only=True) as c:
        summary = db.one(
            c,
            "SELECT COUNT(*) total,COALESCE(SUM(r.total_solicitado),0) total_solicitado,COALESCE(SUM(r.total_aprobado),0) total_aprobado FROM reintegro_solicitudes r WHERE "
            + where,
            tuple(args),
        )
        rows = db.all_rows(
            c,
            """SELECT r.id,r.estado,r.revision,r.moneda,r.total_solicitado,r.total_aprobado,r.creado_at,r.actualizado_at,r.periodo,r.kilometros,
            m.legajo,CONCAT_WS(' ',m.apellido,m.nombre) empleado_nombre
            FROM reintegro_solicitudes r JOIN empleados m ON m.id=r.empleado_id WHERE """
            + where
            + " ORDER BY r.creado_at DESC,r.id DESC LIMIT %s OFFSET %s",
            (*args, per_page, (page - 1) * per_page),
        )
    return dict(items=rows, page=page, per_page=per_page, **summary)


def accessible(c, actor, rid, lock=False):
    where, args = scope(actor)
    row = db.one(
        c,
        "SELECT r.* FROM reintegro_solicitudes r WHERE r.id=%s AND "
        + where
        + (" FOR UPDATE" if lock else ""),
        (rid, *args),
    )
    if not row:
        raise Error("Solicitud no encontrada.", 404)
    return row


def detail(actor, rid):
    with db.transaction(read_only=True) as c:
        row = accessible(c, actor, rid)
        row["gastos"] = db.all_rows(
            c,
            "SELECT id,fecha,concepto,categoria_id,categoria_nombre,importe,decision,motivo,numero_comprobante,emisor FROM reintegro_gastos WHERE solicitud_id=%s AND activo=1 ORDER BY id",
            (rid,),
        )
        photos = db.all_rows(
            c,
            "SELECT f.id,f.gasto_id FROM reintegro_fotos f JOIN reintegro_gastos g ON g.id=f.gasto_id WHERE g.solicitud_id=%s AND g.activo=1",
            (rid,),
        )
        for item in row["gastos"]:
            item["fotos"] = [
                dict(id=f["id"]) for f in photos if f["gasto_id"] == item["id"]
            ]
        row["empleado"] = db.one(
            c,
            "SELECT legajo,nombre,apellido FROM empleados WHERE id=%s AND empresa_id=%s",
            (row["empleado_id"], row["empresa_id"]),
        )
        row["historial"] = db.all_rows(
            c,
            "SELECT accion,creado_at FROM reintegro_auditoria WHERE solicitud_id=%s ORDER BY id",
            (rid,),
        )
        odometer = db.one(
            c,
            "SELECT id FROM reintegro_odometros WHERE solicitud_id=%s AND activo=1",
            (rid,),
        )
        row["foto_odometro_id"] = odometer["id"] if odometer else None
        row["fecha_cierre"] = (
            monthly.deadline(row["periodo"]) if row.get("periodo") else None
        )
        owner = db.one(
            c,
            "SELECT id,empresa_id,sector_id FROM empleados WHERE id=%s",
            (row["empleado_id"],),
        )
        row["puede_editar_empleado"] = False
        if row["estado"] in ("borrador", "devuelta"):
            try:
                monthly.employee_write(c, owner, row.get("periodo"), row)
                row["puede_editar_empleado"] = True
            except Error:
                pass
        duplicates = db.all_rows(
            c,
            """SELECT mine.id FROM reintegro_gastos mine
            WHERE mine.solicitud_id=%s AND mine.activo=1 AND COALESCE(mine.numero_comprobante,'')<>'' AND COALESCE(mine.emisor,'')<>''
            AND EXISTS(SELECT 1 FROM reintegro_gastos g JOIN reintegro_solicitudes r ON r.id=g.solicitud_id
                WHERE r.empresa_id=%s AND r.estado<>'cancelada' AND g.activo=1 AND g.id<>mine.id AND g.numero_comprobante=mine.numero_comprobante AND g.emisor=mine.emisor)""",
            (rid, row["empresa_id"]),
        )
        row["advertencias"] = [
            dict(
                gasto_id=g["id"],
                mensaje="Posible comprobante repetido: coinciden emisor y número. Revisar.",
            )
            for g in duplicates
        ]
        if actor.get("mode") != "empleado":
            row["auditoria"] = db.all_rows(
                c,
                "SELECT usuario_id,empleado_id,accion,datos,creado_at FROM reintegro_auditoria WHERE solicitud_id=%s ORDER BY id",
                (rid,),
            )
    for key in ("contenido_hash", "envio_id", "jefe_id", "revisor_id", "pagado_por"):
        row.pop(key, None)
    return row


def photo(actor, fid):
    with db.transaction(read_only=True) as c:
        meta = db.one(
            c,
            "SELECT g.solicitud_id FROM reintegro_fotos f JOIN reintegro_gastos g ON g.id=f.gasto_id WHERE f.id=%s AND g.activo=1",
            (fid,),
        )
        if not meta:
            raise Error("Foto no encontrada.", 404)
        accessible(c, actor, meta["solicitud_id"])
        return db.one(c, "SELECT contenido FROM reintegro_fotos WHERE id=%s", (fid,))


def odometer_photo(actor, fid):
    with db.transaction(read_only=True) as c:
        row = db.one(
            c,
            "SELECT solicitud_id FROM reintegro_odometros WHERE id=%s AND activo=1",
            (fid,),
        )
        if not row:
            raise Error("Foto no encontrada.", 404)
        accessible(c, actor, row["solicitud_id"])
        return db.one(
            c, "SELECT contenido FROM reintegro_odometros WHERE id=%s", (fid,)
        )


def transition(actor, rid, data):
    action = data.get("accion")
    revision = positive_int(data.get("revision"), "Revisión")
    with db.transaction() as c:
        row = accessible(c, actor, rid, True)
        if row["revision"] != revision:
            raise Error("La solicitud cambió. Recargue antes de continuar.", 409)
        own = row["empleado_id"] == actor.get("empleado_id")
        reason = text_field(data, "motivo", 1000, False)
        updates = {}
        if action == "reabrir":
            if actor.get("mode") != "web" or not actor.get("manage_edit"):
                raise Error("No tiene permiso para reabrir períodos.", 403)
            if not row.get("periodo") or row["estado"] not in ("borrador", "devuelta"):
                raise Error(
                    "Solo puede reabrir borradores o rendiciones devueltas.", 409
                )
            until = date_field(data.get("reabierto_hasta"))
            if (
                not reason
                or until < now_local().date()
                or until > now_local().date() + timedelta(days=31)
            ):
                raise Error(
                    "Indique motivo y un plazo entre hoy y los próximos 31 días."
                )
            updates = dict(reabierto_hasta=until)
            state = row["estado"]
        elif action == "cancelar":
            administrative = actor.get("mode") == "web" and actor.get("manage_delete")
            if (not own and not administrative) or row["estado"] not in (
                "borrador",
                "devuelta",
                "pendiente",
            ):
                raise Error("No puede cancelar esta solicitud.", 409)
            if administrative:
                if not reason:
                    raise Error("Indique el motivo de la cancelación.")
                updates["motivo"] = reason
            elif actor.get("mode") == "empleado":
                owner = db.one(
                    c,
                    "SELECT id,empresa_id,sector_id FROM empleados WHERE id=%s",
                    (row["empleado_id"],),
                )
                monthly.employee_write(c, owner, row.get("periodo"), row)
            state = "cancelada"
        elif action == "pagar":
            if not actor.get("pay") or own:
                raise Error("No tiene permiso para registrar este pago.", 403)
            if row["estado"] != "aprobada":
                raise Error("Solo se pueden pagar solicitudes aprobadas.", 409)
            day = date_field(data.get("fecha_pago"))
            if day > now_local().date() or day < row["revisado_at"].date():
                raise Error("La fecha de pago debe estar entre la aprobación y hoy.")
            updates = dict(
                fecha_pago=day,
                referencia_pago=text_field(data, "referencia_pago", 180),
                pagado_por=actor["user_id"],
                pagado_at=now_local(),
            )
            state = "pagada"
        else:
            if actor.get("mode") == "empleado" or not actor.get("review") or own:
                raise Error(
                    "No puede aprobar su propia solicitud ni actuar sin permiso.", 403
                )
            if not actor.get("review_global") and not db.one(
                c,
                "SELECT id FROM empleados WHERE id=%s AND empresa_id=%s AND reporta_a_empleado_id=%s",
                (row["empleado_id"], row["empresa_id"], actor.get("empleado_id") or 0),
            ):
                raise Error(
                    "Solo el jefe directo actual o RR. HH. pueden revisar esta solicitud.",
                    403,
                )
            if row["estado"] != "pendiente":
                raise Error("La solicitud ya fue revisada.", 409)
            if action not in ("resolver", "devolver", "rechazar"):
                raise Error("Acción inválida.")
            if action in ("devolver", "rechazar") and not reason:
                raise Error("Indique el motivo.")
            updates = dict(
                revisor_id=actor["user_id"], revisado_at=now_local(), motivo=reason
            )
            if action == "devolver":
                state = "devuelta"
            else:
                expenses = db.all_rows(
                    c,
                    "SELECT id,importe FROM reintegro_gastos WHERE solicitud_id=%s AND activo=1",
                    (rid,),
                )
                decisions = data.get("decisiones", [])
                if isinstance(decisions, str):
                    try:
                        decisions = json.loads(decisions)
                    except ValueError:
                        raise Error("Decisiones inválidas.")
                if action == "rechazar":
                    decisions = [
                        dict(id=g["id"], decision="rechazado", motivo=reason)
                        for g in expenses
                    ]
                if not isinstance(decisions, list) or any(
                    not isinstance(d, dict) for d in decisions
                ):
                    raise Error("Decisiones inválidas.")
                mapped = {positive_int(d.get("id"), "Gasto"): d for d in decisions}
                if len(mapped) != len(decisions) or set(mapped) != {
                    g["id"] for g in expenses
                }:
                    raise Error("Revise todos los gastos exactamente una vez.")
                approved = Decimal("0.00")
                for expense in expenses:
                    decision = mapped[expense["id"]]
                    status = decision.get("decision")
                    if status not in ("aprobado", "rechazado"):
                        raise Error("Decisión inválida.")
                    why = text_field(decision, "motivo", 1000, status == "rechazado")
                    if status == "aprobado":
                        approved += expense["importe"]
                    c.execute(
                        "UPDATE reintegro_gastos SET decision=%s,motivo=%s WHERE id=%s",
                        (status, why, expense["id"]),
                    )
                updates["total_aprobado"] = approved
                state = (
                    "aprobada"
                    if approved or (not expenses and action == "resolver")
                    else "rechazada"
                )
        updates.update(estado=state, revision=revision + 1, actualizado_at=now_local())
        c.execute(
            "UPDATE reintegro_solicitudes SET "
            + ",".join(k + "=%s" for k in updates)
            + " WHERE id=%s",
            (*updates.values(), rid),
        )
        audit(
            c,
            row["empresa_id"],
            action,
            dict(
                anterior=row["estado"],
                nuevo=updates,
                decisiones=data.get("decisiones"),
                motivo_accion=reason,
            ),
            rid,
            user=actor.get("user_id"),
            employee=actor.get("empleado_id"),
        )

import csv
import datetime
import io

from extensions import get_db


def _clean(row: dict, key: str, default: str | None = None):
    return (row.get(key) or "").strip() or default


def _bool_si(value: str | None) -> bool:
    return str(value or "").strip().upper() == "SI"


def _parse_optional_int(value: str | None) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return int(float(raw.replace(",", ".")))


def _build_row(row: dict, imported_at: datetime.datetime) -> dict:
    return {
        "codigo_articulo": _clean(row, "Articulo"),
        "descripcion": _clean(row, "Descripcion articulo"),
        "unidades_por_bulto": _parse_optional_int(_clean(row, "Unidades por bulto")) or 0,
        "bultos_por_pallet": _parse_optional_int(_clean(row, "Bultos por pallet")),
        "presentacion_bulto": _clean(row, "Presentacion bulto"),
        "descripcion_presentacion_bulto": _clean(row, "Descripcion presentacion bulto"),
        "presentacion_unidad": _clean(row, "Presentacion unidad"),
        "descripcion_presentacion_unidad": _clean(row, "Descripcion presentacion unidad"),
        "marca": _clean(row, "MARCA"),
        "familia": _clean(row, "FAMILIA"),
        "sabor": _clean(row, "SABOR"),
        "division": _clean(row, "DIVISION"),
        "codigo_barras": _clean(row, "Codigo de barras"),
        "codigo_barras_unidad": _clean(row, "Codigo de barras unidad"),
        "activo_fuente": 1 if _bool_si(_clean(row, "Activo")) else 0,
        "anulado_fuente": 1 if _bool_si(_clean(row, "Anulado")) else 0,
        "movil_fuente": 1 if _bool_si(_clean(row, "Usado en dispositivo movil")) else 0,
        "tipo_producto_fuente": _clean(row, "TIPO DE PRODUCTO") or "",
        "habilitado_pedido": 1,
        "last_import_at": imported_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _is_importable(row: dict) -> bool:
    return (
        _bool_si(_clean(row, "Activo"))
        and not _bool_si(_clean(row, "Anulado"))
        and _bool_si(_clean(row, "Usado en dispositivo movil"))
        and (_clean(row, "TIPO DE PRODUCTO") or "").strip().upper() == "MERCADERIA"
    )


def importar_articulos_desde_csv(stream) -> dict:
    text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text_stream, delimiter=";")

    imported_at = datetime.datetime.now()
    rows_to_import = []
    seen_codes = set()
    errores = []
    total_filas = 0
    ignorados = 0

    for fila_num, row in enumerate(reader, start=2):
        total_filas += 1
        if not _is_importable(row):
            ignorados += 1
            continue

        codigo_articulo = _clean(row, "Articulo")
        descripcion = _clean(row, "Descripcion articulo")
        unidades_por_bulto = _clean(row, "Unidades por bulto")
        if not codigo_articulo:
            errores.append({"fila": fila_num, "codigo_articulo": "", "motivo": "Articulo vacio"})
            continue
        if codigo_articulo in seen_codes:
            errores.append({"fila": fila_num, "codigo_articulo": codigo_articulo, "motivo": "Articulo duplicado en el CSV"})
            continue
        if not descripcion:
            errores.append({"fila": fila_num, "codigo_articulo": codigo_articulo, "motivo": "Descripcion articulo vacia"})
            continue
        if not unidades_por_bulto:
            errores.append({"fila": fila_num, "codigo_articulo": codigo_articulo, "motivo": "Unidades por bulto vacio"})
            continue
        try:
            prepared = _build_row(row, imported_at)
        except ValueError as exc:
            errores.append({"fila": fila_num, "codigo_articulo": codigo_articulo, "motivo": str(exc)})
            continue
        if prepared["unidades_por_bulto"] <= 0:
            errores.append({"fila": fila_num, "codigo_articulo": codigo_articulo, "motivo": "Unidades por bulto debe ser mayor a cero"})
            continue

        seen_codes.add(codigo_articulo)
        rows_to_import.append(prepared)

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        existentes = {}
        if rows_to_import:
            cursor.execute(
                "SELECT codigo_articulo FROM articulos_catalogo_pedidos WHERE codigo_articulo IN (%s)"
                % ",".join(["%s"] * len(rows_to_import)),
                tuple(row["codigo_articulo"] for row in rows_to_import),
            )
            existentes = {row["codigo_articulo"] for row in cursor.fetchall()}

        if rows_to_import:
            cursor.executemany(
                """
                INSERT INTO articulos_catalogo_pedidos
                (
                    codigo_articulo,
                    descripcion,
                    unidades_por_bulto,
                    bultos_por_pallet,
                    presentacion_bulto,
                    descripcion_presentacion_bulto,
                    presentacion_unidad,
                    descripcion_presentacion_unidad,
                    marca,
                    familia,
                    sabor,
                    division,
                    codigo_barras,
                    codigo_barras_unidad,
                    activo_fuente,
                    anulado_fuente,
                    movil_fuente,
                    tipo_producto_fuente,
                    habilitado_pedido,
                    last_import_at
                )
                VALUES (%(codigo_articulo)s,%(descripcion)s,%(unidades_por_bulto)s,%(bultos_por_pallet)s,%(presentacion_bulto)s,%(descripcion_presentacion_bulto)s,%(presentacion_unidad)s,%(descripcion_presentacion_unidad)s,%(marca)s,%(familia)s,%(sabor)s,%(division)s,%(codigo_barras)s,%(codigo_barras_unidad)s,%(activo_fuente)s,%(anulado_fuente)s,%(movil_fuente)s,%(tipo_producto_fuente)s,%(habilitado_pedido)s,%(last_import_at)s)
                ON DUPLICATE KEY UPDATE
                    descripcion = VALUES(descripcion),
                    unidades_por_bulto = VALUES(unidades_por_bulto),
                    bultos_por_pallet = VALUES(bultos_por_pallet),
                    presentacion_bulto = VALUES(presentacion_bulto),
                    descripcion_presentacion_bulto = VALUES(descripcion_presentacion_bulto),
                    presentacion_unidad = VALUES(presentacion_unidad),
                    descripcion_presentacion_unidad = VALUES(descripcion_presentacion_unidad),
                    marca = VALUES(marca),
                    familia = VALUES(familia),
                    sabor = VALUES(sabor),
                    division = VALUES(division),
                    codigo_barras = VALUES(codigo_barras),
                    codigo_barras_unidad = VALUES(codigo_barras_unidad),
                    activo_fuente = VALUES(activo_fuente),
                    anulado_fuente = VALUES(anulado_fuente),
                    movil_fuente = VALUES(movil_fuente),
                    tipo_producto_fuente = VALUES(tipo_producto_fuente),
                    habilitado_pedido = VALUES(habilitado_pedido),
                    last_import_at = VALUES(last_import_at)
                """,
                rows_to_import,
            )

        deshabilitados = 0
        if seen_codes:
            cursor.execute(
                "UPDATE articulos_catalogo_pedidos SET habilitado_pedido = 0 WHERE codigo_articulo NOT IN (%s) AND habilitado_pedido = 1"
                % ",".join(["%s"] * len(seen_codes)),
                tuple(seen_codes),
            )
            deshabilitados = int(cursor.rowcount or 0)

        db.commit()
        creados = sum(1 for row in rows_to_import if row["codigo_articulo"] not in existentes)
        actualizados = len(rows_to_import) - creados
        return {
            "total_filas": total_filas,
            "importables": len(rows_to_import),
            "creados": creados,
            "actualizados": actualizados,
            "deshabilitados": deshabilitados,
            "ignorados": ignorados,
            "errores": errores,
        }
    finally:
        cursor.close()
        db.close()

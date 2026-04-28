"""
Servicio de importación masiva de empleados desde CSV.

Formato esperado del CSV (separado por comas o punto y coma, con encabezados):
legajo, dni, cuil, apellido, nombre, sexo, fecha_nacimiento, email, telefono,
direccion, codigo_postal, fecha_ingreso, tipo_contrato, modalidad, categoria,
obra_social, cod_chess_erp, banco, cbu, numero_emergencia, estado,
sucursal_nombre, sector_nombre, puesto_nombre, password

Campos obligatorios: legajo, dni, apellido, nombre
Password: si viene vacío se usa el DNI como contraseña inicial.
"""

import csv
import datetime
import io
from werkzeug.security import generate_password_hash

from extensions import get_db
from repositories.empleado_repository import create as _create_empleado, exists_unique

# Columnas válidas para enum en DB
_SEXOS = {"masculino", "femenino", "no_binario", "no_informa"}
_ESTADOS = {"activo", "inactivo", "suspendido"}
_TIPO_CONTRATO = {"efectivo", "temporal", "pasantia", "otro"}
_MODALIDAD = {"presencial", "remoto", "hibrido"}
_EXPECTED_COLUMNS = {
    "legajo",
    "dni",
    "cuil",
    "apellido",
    "nombre",
    "sexo",
    "fecha_nacimiento",
    "email",
    "telefono",
    "direccion",
    "codigo_postal",
    "fecha_ingreso",
    "tipo_contrato",
    "modalidad",
    "fecha_baja",
    "categoria",
    "obra_social",
    "cod_chess_erp",
    "banco",
    "cbu",
    "numero_emergencia",
    "estado",
    "sucursal_nombre",
    "sector_nombre",
    "puesto_nombre",
    "password",
}
_REQUIRED_COLUMNS = {"legajo", "dni", "apellido", "nombre"}
_DATE_FIELDS = ("fecha_nacimiento", "fecha_ingreso", "fecha_baja")
_DELIMITERS = (",", ";", "\t")


def _lookup_sucursal(cursor, empresa_id: int, nombre: str):
    if not nombre:
        return None
    cursor.execute(
        "SELECT id FROM sucursales WHERE empresa_id = %s AND nombre = %s AND activa = 1 LIMIT 1",
        (empresa_id, nombre.strip()),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def _lookup_sector(cursor, empresa_id: int, nombre: str):
    if not nombre:
        return None
    cursor.execute(
        "SELECT id FROM sectores WHERE empresa_id = %s AND nombre = %s AND activo = 1 LIMIT 1",
        (empresa_id, nombre.strip()),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def _lookup_puesto(cursor, empresa_id: int, nombre: str):
    if not nombre:
        return None
    cursor.execute(
        "SELECT id FROM puestos WHERE empresa_id = %s AND nombre = %s AND activo = 1 LIMIT 1",
        (empresa_id, nombre.strip()),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def _clean(row: dict, key: str, default=None):
    return (row.get(key) or "").strip() or default


def _normalize_key(key) -> str:
    return str(key or "").strip().lower().lstrip("\ufeff")


def _parse_csv_line(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), [])


def _find_header(lines: list[str]) -> tuple[int, str]:
    best = None
    for idx, line in enumerate(lines):
        if not str(line or "").strip():
            continue
        for delimiter in _DELIMITERS:
            headers = [_normalize_key(value) for value in _parse_csv_line(line, delimiter)]
            header_set = set(headers)
            required_matches = len(header_set & _REQUIRED_COLUMNS)
            expected_matches = len(header_set & _EXPECTED_COLUMNS)
            score = (required_matches, expected_matches)
            if best is None or score > best[0]:
                best = (score, idx, delimiter, headers)
            if _REQUIRED_COLUMNS.issubset(header_set):
                return idx, delimiter

    if best and best[0][1]:
        missing = sorted(_REQUIRED_COLUMNS - set(best[3]))
        raise ValueError(f"Columnas obligatorias faltantes: {', '.join(missing)}")
    raise ValueError(
        "No se encontraron encabezados CSV validos. "
        "El archivo debe incluir columnas: legajo, dni, apellido, nombre."
    )


def _build_reader(stream):
    raw = stream.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = str(raw or "")

    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError("El archivo CSV esta vacio.")

    header_idx, delimiter = _find_header(lines)
    csv_text = "\n".join(lines[header_idx:])
    return csv.DictReader(io.StringIO(csv_text), delimiter=delimiter), header_idx


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[_normalize_key(key)] = (value or "").strip()
    return normalized


def _is_template_label_row(row: dict) -> bool:
    legajo = _clean(row, "legajo", "").lower()
    dni = _clean(row, "dni", "").lower()
    apellido = _clean(row, "apellido", "").lower()
    nombre = _clean(row, "nombre", "").lower()
    return (
        legajo.startswith("legajo")
        and dni.startswith("dni")
        and apellido.startswith("apellido")
        and nombre.startswith("nombre")
    )


def _is_template_example_row(row: dict) -> bool:
    return (
        _clean(row, "legajo") == "001"
        and _clean(row, "dni") == "12345678"
        and _clean(row, "apellido") == "Perez"
        and _clean(row, "nombre") == "Juan"
    )


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_dates(row: dict) -> list[str]:
    errors = []
    for field in _DATE_FIELDS:
        value = _clean(row, field)
        if not value:
            continue
        normalized = _parse_date(value)
        if not normalized:
            errors.append(f"{field} invalida '{value}'")
        else:
            row[field] = normalized
    return errors


def _validate_row(row: dict, fila_num: int):
    errors = []
    if not _clean(row, "legajo"):
        errors.append("legajo vacío")
    if not _clean(row, "dni"):
        errors.append("dni vacío")
    if not _clean(row, "apellido"):
        errors.append("apellido vacío")
    if not _clean(row, "nombre"):
        errors.append("nombre vacío")

    sexo = _clean(row, "sexo", "no_informa").lower()
    if sexo not in _sexos_validos():
        errors.append(f"sexo inválido '{sexo}'")

    estado = _clean(row, "estado", "activo").lower()
    if estado not in _ESTADOS:
        errors.append(f"estado inválido '{estado}'")

    tipo_contrato = _clean(row, "tipo_contrato")
    if tipo_contrato and tipo_contrato.lower() not in _TIPO_CONTRATO:
        errors.append(f"tipo_contrato inválido '{tipo_contrato}'")

    modalidad = _clean(row, "modalidad", "presencial").lower()
    if modalidad not in _MODALIDAD:
        errors.append(f"modalidad inválida '{modalidad}'")

    cod_chess = _clean(row, "cod_chess_erp")
    if cod_chess:
        try:
            int(cod_chess)
        except ValueError:
            errors.append(f"cod_chess_erp debe ser un número entero")

    return errors


def _sexos_validos():
    return _SEXOS


def importar_desde_csv(stream, empresa_id: int) -> dict:
    """
    Lee el stream del CSV, valida e inserta cada fila.
    Devuelve un dict con:
      - creados: int
      - omitidos: int (dni/legajo duplicados)
      - errores: list[dict(fila, dni, motivo)]
    """
    reader, header_idx = _build_reader(stream)

    creados = 0
    omitidos = 0
    errores = []

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        for fila_num, row in enumerate(reader, start=header_idx + 2):
            row = _normalize_row(row)
            if not any(row.values()) or _is_template_label_row(row) or _is_template_example_row(row):
                continue

            dni = _clean(row, "dni", "")
            legajo = _clean(row, "legajo", "")

            # Validar campos
            row_errors = _normalize_dates(row)
            row_errors.extend(_validate_row(row, fila_num))
            if row_errors:
                errores.append({
                    "fila": fila_num,
                    "dni": dni,
                    "motivo": "; ".join(row_errors),
                })
                continue

            # Verificar duplicados
            if exists_unique("dni", dni):
                omitidos += 1
                errores.append({
                    "fila": fila_num,
                    "dni": dni,
                    "motivo": f"DNI {dni} ya existe (omitido)",
                })
                continue

            if exists_unique("legajo", legajo):
                omitidos += 1
                errores.append({
                    "fila": fila_num,
                    "dni": dni,
                    "motivo": f"Legajo {legajo} ya existe (omitido)",
                })
                continue

            # Resolver FK por nombre
            sucursal_id = _lookup_sucursal(cursor, empresa_id, _clean(row, "sucursal_nombre"))
            sector_id = _lookup_sector(cursor, empresa_id, _clean(row, "sector_nombre"))
            puesto_id = _lookup_puesto(cursor, empresa_id, _clean(row, "puesto_nombre"))

            # Password: usar DNI si no viene
            raw_password = _clean(row, "password") or dni
            password_hash = generate_password_hash(raw_password)

            cod_chess_raw = _clean(row, "cod_chess_erp")

            data = {
                "empresa_id": empresa_id,
                "sucursal_id": sucursal_id,
                "sector_id": sector_id,
                "puesto_id": puesto_id,
                "legajo": legajo,
                "dni": dni,
                "cuil": _clean(row, "cuil"),
                "nombre": _clean(row, "nombre"),
                "apellido": _clean(row, "apellido"),
                "fecha_nacimiento": _clean(row, "fecha_nacimiento"),
                "sexo": _clean(row, "sexo", "no_informa").lower(),
                "email": _clean(row, "email"),
                "telefono": _clean(row, "telefono"),
                "direccion": _clean(row, "direccion"),
                "codigo_postal": _clean(row, "codigo_postal"),
                "fecha_ingreso": _clean(row, "fecha_ingreso"),
                "tipo_contrato": _clean(row, "tipo_contrato", "").lower() or None,
                "modalidad": _clean(row, "modalidad", "presencial").lower(),
                "fecha_baja": _clean(row, "fecha_baja"),
                "categoria": _clean(row, "categoria"),
                "obra_social": _clean(row, "obra_social"),
                "cod_chess_erp": int(cod_chess_raw) if cod_chess_raw else None,
                "banco": _clean(row, "banco"),
                "cbu": _clean(row, "cbu"),
                "numero_emergencia": _clean(row, "numero_emergencia"),
                "estado": _clean(row, "estado", "activo").lower(),
                "password_hash": password_hash,
                "foto": None,
            }

            try:
                _create_empleado(data)
                creados += 1
            except Exception as exc:
                errores.append({
                    "fila": fila_num,
                    "dni": dni,
                    "motivo": f"Error al insertar: {exc}",
                })

    finally:
        cursor.close()
        db.close()

    return {
        "creados": creados,
        "omitidos": omitidos,
        "errores": errores,
    }

"""
Importacion de clientes desde CSV.

El archivo original puede traer muchas columnas; solo se persiste el subconjunto
necesario para el modulo de feedback.
"""

from __future__ import annotations

import csv
import io
import unicodedata

from repositories.feedback_cliente_repository import upsert as upsert_cliente


_DELIMITERS = (",", ";", "\t")
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _decode_csv(raw) -> str:
    if not isinstance(raw, bytes):
        return str(raw or "")

    last_error = None
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    raise ValueError(f"No se pudo leer el archivo CSV: {last_error}")


def _normalize_key(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    raw = raw.encode("ascii", "ignore").decode("ascii")
    pieces = []
    last_underscore = False
    for char in raw:
        if char.isalnum():
            pieces.append(char)
            last_underscore = False
        else:
            if not last_underscore:
                pieces.append("_")
                last_underscore = True
    return "".join(pieces).strip("_")


def _clean(row: dict, *keys: str, default=None):
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return default


def _parse_float(value):
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _is_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "s", "y", "anulado"}


def _parse_csv(text: str):
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError("El archivo CSV esta vacio.")

    header_line = None
    delimiter = ","
    for line in lines[:10]:
        if not line.strip():
            continue
        for candidate in _DELIMITERS:
            columns = [_normalize_key(value) for value in csv.reader([line], delimiter=candidate).__next__()]
            if {"cliente", "razon_social"}.issubset(set(columns)):
                header_line = line
                delimiter = candidate
                break
        if header_line:
            break
    if not header_line:
        for candidate in _DELIMITERS:
            columns = [_normalize_key(value) for value in csv.reader([lines[0]], delimiter=candidate).__next__()]
            if {"cliente", "razon_social"}.issubset(set(columns)):
                header_line = lines[0]
                delimiter = candidate
                break
    if not header_line:
        raise ValueError(
            "No se encontraron encabezados validos. "
            "El archivo debe incluir al menos las columnas Cliente y Razon social."
        )

    header_index = lines.index(header_line)
    normalized_text = "\n".join(lines[header_index:])
    reader = csv.DictReader(io.StringIO(normalized_text), delimiter=delimiter)
    return reader, header_index


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[_normalize_key(key)] = (value or "").strip()
    return normalized


def _build_payload(row: dict) -> dict:
    codigo_externo = _clean(row, "cliente", "codigo_cliente")
    razon_social = _clean(row, "razon_social")
    if not codigo_externo or not razon_social:
        raise ValueError("Cliente y Razon social son obligatorios.")

    return {
        "sucursal_origen": _parse_int(_clean(row, "sucursal")),
        "codigo_externo": codigo_externo,
        "razon_social": razon_social,
        "nombre_fantasia": _clean(row, "nombre_de_fantasia", "nombre_fantasia"),
        "telefonos": _clean(row, "telefonos"),
        "movil": _clean(row, "movil"),
        "email": _clean(row, "e_mail", "email"),
        "domicilio": _clean(row, "domicilio"),
        "localidad": _clean(row, "localidad"),
        "descripcion_localidad": _clean(row, "descripcion_localidad"),
        "provincia": _clean(row, "provincia"),
        "descripcion_provincia": _clean(row, "descripcion_provincia"),
        "tipo_codigo": _clean(row, "ramo"),
        "tipo_descripcion": _clean(row, "descripcion_ramo"),
        "comentario": _clean(row, "comentario"),
        # El CSV original entrega X=longitud y Y=latitud.
        "latitud": _parse_float(_clean(row, "coord_y")),
        "longitud": _parse_float(_clean(row, "coord_x")),
        "activo": not _is_truthy(_clean(row, "anulado")),
    }


def importar_clientes_desde_csv(stream) -> dict:
    raw = stream.read()
    text = _decode_csv(raw)

    reader, header_index = _parse_csv(text)

    total_filas = 0
    importadas = 0
    creados = 0
    actualizados = 0
    errores: list[dict] = []

    for row_number, row in enumerate(reader, start=header_index + 2):
        normalized = _normalize_row(row)
        if not any(normalized.values()):
            continue
        total_filas += 1
        try:
            payload = _build_payload(normalized)
            cliente_id, was_created = upsert_cliente(payload)
            importadas += 1
            if was_created:
                creados += 1
            else:
                actualizados += 1
        except Exception as exc:
            errores.append(
                {
                    "fila": row_number,
                    "codigo_externo": _clean(normalized, "cliente", "codigo_cliente"),
                    "motivo": str(exc),
                }
            )

    return {
        "total_filas": total_filas,
        "importadas": importadas,
        "creados": creados,
        "actualizados": actualizados,
        "errores": len(errores),
        "detalle_errores": errores,
    }

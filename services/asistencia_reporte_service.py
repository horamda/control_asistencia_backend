import csv
import datetime
import io


ASISTENCIA_REPORTE_HEADERS = [
    "MES",
    "FECHA",
    "HORA",
    "PUERTA",
    "TIPO MOV",
    "CODIGO",
    "NOMBRE",
    "SECTOR",
]


def _fecha_parts(value):
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return value, f"{value.day}/{value.month}/{value.year}"

    text = str(value or "").strip()
    if not text:
        return None, ""

    for candidate in (text, text[:10]):
        try:
            parsed = datetime.date.fromisoformat(candidate)
            return parsed, f"{parsed.day}/{parsed.month}/{parsed.year}"
        except ValueError:
            continue

    parts = text.split("/")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        day, month, year = (int(parts[0]), int(parts[1]), int(parts[2]))
        try:
            parsed = datetime.date(year, month, day)
        except ValueError:
            return None, text
        return parsed, f"{parsed.day}/{parsed.month}/{parsed.year}"

    return None, text


def _hora_text(value):
    if isinstance(value, datetime.datetime):
        value = value.time()
    if isinstance(value, datetime.time):
        return f"{value.hour:02d}:{value.minute:02d}"

    text = str(value or "").strip()
    if not text:
        return ""

    candidates = [text]
    if len(text) == 5:
        candidates.append(f"{text}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return f"{parsed.hour:02d}:{parsed.minute:02d}"
        except ValueError:
            continue

    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text[:5]


def build_asistencia_reporte_row(row: dict) -> list:
    fecha_obj, fecha_text = _fecha_parts(row.get("fecha"))
    accion = str(row.get("accion") or "").strip().lower()
    if accion == "ingreso":
        tipo_mov = "Entrada"
    elif accion == "egreso":
        tipo_mov = "Salida"
    else:
        tipo_mov = accion.capitalize() if accion else ""

    nombre = (
        f"{row.get('apellido') or ''} {row.get('nombre') or ''}".strip().upper()
        or "-"
    )
    codigo = row.get("legajo") or row.get("dni") or row.get("empleado_id") or ""
    return [
        fecha_obj.month if fecha_obj else "",
        fecha_text,
        _hora_text(row.get("hora")),
        row.get("sucursal_nombre") or "-",
        tipo_mov,
        codigo,
        nombre,
        row.get("sector_nombre") or "-",
    ]


def build_asistencia_reporte_csv(rows) -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(ASISTENCIA_REPORTE_HEADERS)
    for row in rows:
        writer.writerow(build_asistencia_reporte_row(row))
    return "\ufeff" + out.getvalue()

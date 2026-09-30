"""Importación CSV de vehículos nuevos, con prevalidación y guardado atómico."""
import csv
import io
import unicodedata

from repositories import carga_repository as repo
from services.carga_service import CargaError, audit, positive_int, text_field

MAX_BYTES = 1024 * 1024
MAX_ROWS = 500
COLUMNS = ('numero', 'patente', 'sucursal_id', 'descripcion', 'activo')


def _key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).strip())
                   if not unicodedata.combining(c)).casefold()


def parse_file(file, default_branch=None):
    if not file or not str(file.filename or '').lower().endswith('.csv'):
        raise CargaError('Seleccione un archivo CSV (.csv). Puede exportarlo desde Excel.')
    raw = file.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise CargaError('El CSV debe tener contenido y pesar hasta 1 MB.')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('cp1252', errors='strict')
    try:
        delimiter = csv.Sniffer().sniff(content[:8192], delimiters=';,\t').delimiter
    except csv.Error:
        delimiter = ';'
    reader = csv.reader(io.StringIO(content, newline=''), delimiter=delimiter, strict=True)
    try:
        headers = [_key(h) for h in next(reader)]
        if len(set(headers)) != len(headers) or not {'numero', 'patente'}.issubset(headers) or set(headers) - set(COLUMNS):
            raise CargaError('Encabezados inválidos. Use la plantilla: numero, patente, sucursal_id, descripcion, activo.')
        rows, errors = [], []
        seen_numbers, seen_plates = set(), set()
        count = 0
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            count += 1
            if count > MAX_ROWS:
                raise CargaError(f'Se permiten hasta {MAX_ROWS} vehículos por archivo.')
            line = reader.line_num
            try:
                if len(values) != len(headers):
                    raise CargaError('La cantidad de columnas no coincide con los encabezados.')
                data = dict(zip(headers, values))
                numero = text_field(data, 'numero', 40).upper()
                patente = text_field(data, 'patente', 20).upper()
                if len(numero) > 40 or len(patente) > 20:
                    raise CargaError('Número o patente demasiado largos.')
                state = _key((data.get('activo') or '').strip() or '1')
                if state not in ('1', '0', 'si', 'no', 'true', 'false'):
                    raise CargaError('Activo debe ser 1/0 o Sí/No.')
                branch = positive_int((data.get('sucursal_id') or '').strip() or default_branch, 'Sucursal')
                if _key(numero) in seen_numbers or _key(patente) in seen_plates:
                    raise CargaError('Número o patente repetidos dentro del archivo.')
                seen_numbers.add(_key(numero))
                seen_plates.add(_key(patente))
                rows.append(dict(fila=line, numero=numero, patente=patente, sucursal_id=branch,
                    descripcion=text_field(data, 'descripcion', 200, False), activo=int(state in ('1', 'si', 'true'))))
            except CargaError as exc:
                errors.append({'fila': line, 'mensaje': str(exc)})
        if not count:
            raise CargaError('El archivo no contiene vehículos.')
        return rows, errors
    except (csv.Error, StopIteration) as exc:
        raise CargaError('CSV inválido. Revise separadores, comillas y encabezados.') from exc


def _plan(cursor, rows, empresa_id):
    branches = {r['id']: r['nombre'] for r in repo.all_rows(cursor,
        'SELECT id, nombre FROM sucursales WHERE empresa_id=%s AND activa=1', (empresa_id,))}
    plan, errors = [], []
    for row in rows:
        entry = dict(row)
        if row['sucursal_id'] not in branches:
            errors.append({'fila': row['fila'], 'mensaje': 'La sucursal no está activa o no pertenece a la empresa seleccionada.'})
            continue
        existing = repo.all_rows(cursor, 'SELECT * FROM carga_camiones WHERE empresa_id=%s AND (numero=%s OR patente=%s)',
            (empresa_id, row['numero'], row['patente']))
        entry['sucursal_nombre'] = branches[row['sucursal_id']]
        entry['accion'] = 'Crear'
        if existing:
            if len(existing) == 1 and all(existing[0][k] == row[k] for k in ('numero', 'patente', 'sucursal_id', 'descripcion', 'activo')):
                entry['accion'] = 'Ya existe; omitir'
            else:
                errors.append({'fila': row['fila'], 'mensaje': 'El número o la patente ya existe con otros datos. Corrija el CSV o edite el vehículo desde el catálogo.'})
                continue
        plan.append(entry)
    return plan, errors


def preview(rows, empresa_id):
    with repo.transaction() as c:
        return _plan(c, rows, empresa_id)


def import_rows(rows, empresa_id, user_id):
    if not rows or len(rows) > MAX_ROWS:
        raise CargaError('Cantidad de filas inválida. Vuelva a validar el archivo.')
    with repo.transaction() as c:
        # Mismo bloqueo que el CRUD: serializa altas para esta empresa.
        if not repo.one(c, 'SELECT id FROM empresas WHERE id=%s FOR UPDATE', (empresa_id,)):
            raise CargaError('Empresa no encontrada.', 404)
        plan, errors = _plan(c, rows, empresa_id)
        if errors:
            return {'creados': 0, 'omitidos': 0, 'errores': errors}
        created, skipped = 0, 0
        for item in plan:
            if item['accion'] != 'Crear':
                skipped += 1
                continue
            values = {k: item[k] for k in COLUMNS}
            values['empresa_id'] = empresa_id
            record_id = repo.insert(c, 'carga_camiones', values)
            audit(c, empresa_id, user_id, 'camiones', record_id, None, {**values, 'fuente': 'importacion_csv'})
            created += 1
        return {'creados': created, 'omitidos': skipped, 'errores': []}

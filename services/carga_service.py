"""Reglas de carga y recarga. Fechas del servidor, limites [desde, hasta)."""
import hashlib
import io
import json
import re
import warnings
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError
from repositories import carga_repository as repo

ARGENTINA = timezone(timedelta(hours=-3))
MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 5 * 1024 * 1024


class CargaError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now_local():
    return datetime.now(ARGENTINA).replace(tzinfo=None)


def in_window(moment, start, end):
    minute = moment.hour * 60 + moment.minute
    return int(start) <= minute < int(end)


def text_field(data, key, limit, required=True):
    value = str(data.get(key) or '').strip()
    if (required and not value) or len(value) > limit:
        raise CargaError(f'{key}: complete el campo (máximo {limit} caracteres).')
    return value


def positive_int(value, field):
    try:
        result = int(str(value))
        if result <= 0:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise CargaError(f'{field}: seleccione un valor válido.')


def clock_minutes(value):
    if value == '24:00':
        return 1440
    if not re.fullmatch(r'\d{2}:\d{2}', str(value or '')):
        raise CargaError('Use horarios HH:MM, o 24:00 para fin del día.')
    hour, minute = map(int, value.split(':'))
    if hour > 23 or minute > 59:
        raise CargaError('Horario inválido.')
    return hour * 60 + minute


def format_minutes(value):
    return f'{int(value) // 60:02d}:{int(value) % 60:02d}'


def date_field(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise CargaError('Fecha inválida. Use AAAA-MM-DD.')


def eligible(c, employee):
    if not employee or not employee.get('activo'):
        return False
    return bool(repo.one(c, '''SELECT cp.puesto_id FROM carga_puestos cp
        JOIN puestos p ON p.id=cp.puesto_id AND p.empresa_id=cp.empresa_id AND p.activo=1
        WHERE cp.empresa_id=%s AND (cp.puesto_id=%s OR EXISTS (
          SELECT 1 FROM empleado_puestos ep WHERE ep.empleado_id=%s AND ep.empresa_id=cp.empresa_id
          AND ep.puesto_id=cp.puesto_id AND ep.activo=1)) LIMIT 1''',
        (employee['empresa_id'], employee.get('puesto_id'), employee['id'])))


def config(employee):
    moment = now_local()
    with repo.transaction() as c:
        allowed = eligible(c, employee)
        has_history = bool(repo.one(c, 'SELECT id FROM carga_validaciones WHERE empleado_id=%s AND empresa_id=%s LIMIT 1', (employee['id'], employee['empresa_id'])))
        trucks = repo.all_rows(c, '''SELECT t.id, t.numero, t.patente, t.sucursal_id, s.nombre sucursal_nombre,
            EXISTS(SELECT 1 FROM carga_validaciones v WHERE v.camion_id=t.id AND v.fecha=%s AND v.tipo='inicial') tiene_inicial
            FROM carga_camiones t JOIN sucursales s ON s.id=t.sucursal_id
            WHERE t.empresa_id=%s AND t.activo=1 ORDER BY t.numero''',
            (moment.date(), employee['empresa_id'])) if allowed else []
        schedules = repo.all_rows(c, '''SELECT id, nombre, tipo, sucursal_id, desde_minuto, hasta_minuto FROM carga_horarios
            WHERE empresa_id=%s AND activo=1 AND vigente_desde<=%s AND (vigente_hasta IS NULL OR vigente_hasta>=%s)''',
            (employee['empresa_id'], moment.date(), moment.date())) if allowed else []
    return {'habilitado': allowed, 'tiene_historial': has_history, 'camiones': trucks, 'horarios': schedules,
            'fecha_servidor': moment.isoformat() + '-03:00', 'zona_horaria': 'America/Argentina/Buenos_Aires',
            'max_fotos': MAX_PHOTOS, 'max_foto_bytes': MAX_PHOTO_BYTES}


def prepare_photos(files):
    if len(files) > MAX_PHOTOS:
        raise CargaError(f'Se permiten hasta {MAX_PHOTOS} fotos.')
    result = []
    for file in files:
        raw = file.read(MAX_PHOTO_BYTES + 1)
        if not raw or len(raw) > MAX_PHOTO_BYTES:
            raise CargaError('Cada foto debe tener contenido y pesar hasta 5 MB.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 20_000_000:
                        raise CargaError('Use fotos JPG, PNG o WEBP de hasta 20 megapíxeles.')
                    source.load()
                    normalized = ImageOps.exif_transpose(source).convert('RGB')
                    normalized.thumbnail((1800, 1800))
                    buffer = io.BytesIO()
                    normalized.save(buffer, format='JPEG', quality=80, optimize=True)
                    content = buffer.getvalue()
                    if len(content) > 2 * 1024 * 1024:
                        raise CargaError('La imagen es demasiado grande luego de comprimirla.')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise CargaError('El archivo no es una imagen válida.')
        result.append({'contenido': content, 'sha256': hashlib.sha256(raw).hexdigest()})
    return result


def create(employee_id, data, files):
    camion_id = positive_int(data.get('camion_id'), 'Camión')
    consolidado = text_field(data, 'consolidado', 64).upper()
    tipo = data.get('tipo')
    if tipo not in ('inicial', 'recarga'):
        raise CargaError('Seleccione carga inicial o recarga.')
    raw_valida = data.get('valida')
    if raw_valida not in (True, False, 'true', 'false', '1', '0') or raw_valida is None:
        raise CargaError('Indique explícitamente si valida la carga: Sí o No.')
    valida = raw_valida in (True, 'true', '1')
    observaciones = text_field(data, 'observaciones', 2000, required=not valida)
    try:
        envio_id = str(UUID(str(data.get('envio_id'))))
    except (ValueError, TypeError, AttributeError):
        raise CargaError('envio_id debe ser un UUID y conservarse al reintentar.')
    origen = data.get('origen', 'app')
    if origen not in ('app', 'web'):
        raise CargaError('Origen inválido.')
    photos = prepare_photos(files)
    fingerprint = hashlib.sha256(json.dumps([camion_id, consolidado, tipo, valida, observaciones,
        [p['sha256'] for p in photos]], ensure_ascii=False).encode()).hexdigest()
    with repo.transaction() as c:
        employee = repo.one(c, '''SELECT e.*, s.nombre sucursal_nombre, p.nombre puesto_nombre
            FROM empleados e LEFT JOIN sucursales s ON s.id=e.sucursal_id AND s.empresa_id=e.empresa_id
            LEFT JOIN puestos p ON p.id=e.puesto_id WHERE e.id=%s''', (employee_id,))
        if not eligible(c, employee):
            raise CargaError('Solo los puestos de chofer y ayudante habilitados pueden validar cargas.', 403)
        empresa_id = employee['empresa_id']
        # Serializa envios del mismo camion, incluso entre distintos empleados.
        truck = repo.one(c, 'SELECT * FROM carga_camiones WHERE id=%s AND empresa_id=%s FOR UPDATE', (camion_id, empresa_id))
        if not truck:
            raise CargaError('Camión no disponible.', 404)
        previous = repo.one(c, 'SELECT id, envio_hash FROM carga_validaciones WHERE empresa_id=%s AND empleado_id=%s AND envio_id=%s FOR UPDATE', (empresa_id, employee_id, envio_id))
        if previous:
            if previous['envio_hash'] != fingerprint:
                raise CargaError('Ese envío ya se utilizó con otros datos. Inicie un nuevo registro.', 409)
            return previous['id'], False
        if not truck['activo']:
            raise CargaError('El camión está inactivo.', 409)
        if not employee.get('sucursal_id') or not employee.get('sucursal_nombre'):
            raise CargaError('El empleado debe tener una sucursal asignada en su empresa.', 409)
        if not str(employee.get('legajo') or '').strip():
            raise CargaError('El empleado debe tener un número de legajo asignado.', 409)
        moment = now_local()
        initial = repo.one(c, "SELECT id FROM carga_validaciones WHERE camion_id=%s AND fecha=%s AND tipo='inicial' FOR UPDATE", (camion_id, moment.date()))
        if tipo == 'inicial' and initial:
            raise CargaError('Este camión ya tiene una carga inicial hoy. Registre una recarga.', 409)
        if tipo == 'recarga' and not initial:
            raise CargaError('Primero debe registrarse la carga inicial del camión de hoy, aunque esté fuera de horario.', 409)
        if repo.one(c, 'SELECT id FROM carga_validaciones WHERE camion_id=%s AND fecha=%s AND consolidado=%s FOR UPDATE', (camion_id, moment.date(), consolidado)):
            raise CargaError('Ese consolidado ya fue registrado para este camión hoy.', 409)
        schedules = repo.all_rows(c, '''SELECT * FROM carga_horarios WHERE empresa_id=%s AND tipo=%s AND activo=1
            AND (sucursal_id=%s OR sucursal_id IS NULL) AND vigente_desde<=%s
            AND (vigente_hasta IS NULL OR vigente_hasta>=%s) FOR UPDATE''',
            (empresa_id, tipo, truck['sucursal_id'], moment.date(), moment.date()))
        scoped = [h for h in schedules if h['sucursal_id'] == truck['sucursal_id']]
        effective = scoped or [h for h in schedules if h['sucursal_id'] is None]
        if len(effective) != 1:
            raise CargaError('No hay un horario único vigente para este vehículo y tipo de carga. Contacte al administrador.', 409)
        schedule = effective[0]
        truck_branch = repo.one(c, 'SELECT nombre FROM sucursales WHERE id=%s AND empresa_id=%s', (truck['sucursal_id'], empresa_id))
        if not truck_branch:
            raise CargaError('La sucursal del camión no pertenece a la empresa.', 409)
        values = dict(empresa_id=empresa_id, empleado_id=employee_id, legajo=str(employee.get('legajo') or ''),
            empleado_nombre=f"{employee.get('apellido') or ''} {employee.get('nombre') or ''}".strip(),
            sucursal_empleado_id=employee['sucursal_id'], sucursal_empleado_nombre=employee['sucursal_nombre'],
            puesto_nombre=employee.get('puesto_nombre') or '', camion_id=camion_id,
            camion_numero=truck['numero'], camion_patente=truck['patente'], sucursal_camion_id=truck['sucursal_id'],
            sucursal_camion_nombre=truck_branch['nombre'], fecha=moment.date(), registrado_at=moment,
            tipo=tipo, consolidado=consolidado, valida=int(valida), observaciones=observaciones,
            en_horario=int(in_window(moment, schedule['desde_minuto'], schedule['hasta_minuto'])),
            horario_id=schedule['id'], horario_nombre=schedule['nombre'], desde_minuto=schedule['desde_minuto'],
            hasta_minuto=schedule['hasta_minuto'], origen=origen, envio_id=envio_id, envio_hash=fingerprint)
        record_id = repo.insert(c, 'carga_validaciones', values)
        for photo in photos:
            repo.insert(c, 'carga_fotos', {'validacion_id': record_id, **photo})
        return record_id, True


def audit(c, empresa_id, user_id, entity, record_id, before, after):
    repo.insert(c, 'carga_auditoria', dict(empresa_id=empresa_id, usuario_id=user_id, entidad=entity,
        registro_id=record_id, detalle=json.dumps({'antes': before, 'despues': after}, default=str, ensure_ascii=False)))


def save_catalog(kind, record_id, empresa_id, user_id, data):
    if kind not in ('camiones', 'horarios'):
        raise CargaError('Catálogo desconocido.', 404)
    table = 'carga_' + kind
    with repo.transaction() as c:
        # Un unico lock de configuracion por empresa evita carreras entre altas/ediciones.
        if not repo.one(c, 'SELECT id FROM empresas WHERE id=%s FOR UPDATE', (empresa_id,)):
            raise CargaError('Empresa no encontrada.', 404)
        before = repo.one(c, f'SELECT * FROM {table} WHERE id=%s AND empresa_id=%s FOR UPDATE', (record_id, empresa_id)) if record_id else None
        if record_id and not before:
            raise CargaError('Registro no encontrado.', 404)
        branch = positive_int(data['sucursal_id'], 'Sucursal') if data.get('sucursal_id') else None
        if branch and not repo.one(c, 'SELECT id FROM sucursales WHERE id=%s AND empresa_id=%s', (branch, empresa_id)):
            raise CargaError('La sucursal no pertenece a la empresa.')
        values = {'empresa_id': empresa_id, 'sucursal_id': branch, 'activo': int(str(data.get('activo', '0')) == '1')}
        if kind == 'camiones':
            if not branch:
                raise CargaError('Seleccione la sucursal del vehículo.')
            values.update(numero=text_field(data, 'numero', 40).upper(), patente=text_field(data, 'patente', 20).upper(),
                descripcion=text_field(data, 'descripcion', 200, False))
            duplicate = repo.one(c, 'SELECT id FROM carga_camiones WHERE empresa_id=%s AND (numero=%s OR patente=%s) AND id<>%s',
                (empresa_id, values['numero'], values['patente'], record_id or 0))
            if duplicate:
                raise CargaError('Ya existe un vehículo con ese número o patente.', 409)
        else:
            if data.get('tipo') not in ('inicial', 'recarga'):
                raise CargaError('Tipo de horario inválido.')
            start, end = clock_minutes(data.get('desde')), clock_minutes(data.get('hasta'))
            if start >= end:
                raise CargaError('El horario Desde debe ser anterior a Hasta. No se admiten cruces de medianoche.')
            first = date_field(data.get('vigente_desde'))
            last = date_field(data['vigente_hasta']) if data.get('vigente_hasta') else None
            if last and last < first:
                raise CargaError('La vigencia final debe ser igual o posterior a la inicial.')
            values.update(nombre=text_field(data, 'nombre', 100), tipo=data['tipo'], desde_minuto=start,
                hasta_minuto=end, vigente_desde=first, vigente_hasta=last)
            if values['activo'] and repo.one(c, '''SELECT id FROM carga_horarios WHERE empresa_id=%s AND sucursal_id <=> %s
                AND tipo=%s AND activo=1 AND id<>%s AND vigente_desde<=%s AND (vigente_hasta IS NULL OR vigente_hasta>=%s)''',
                (empresa_id, branch, values['tipo'], record_id or 0, last or date(9999, 12, 31), first)):
                raise CargaError('Ya existe una regla activa de este tipo y alcance con vigencia superpuesta.', 409)
        if record_id:
            c.execute(f"UPDATE {table} SET {', '.join(k + '=%s' for k in values)} WHERE id=%s AND empresa_id=%s", (*values.values(), record_id, empresa_id))
        else:
            record_id = repo.insert(c, table, values)
        audit(c, empresa_id, user_id, kind, record_id, before, values)
        return record_id


def save_positions(empresa_id, user_id, positions):
    ids = sorted(set(positive_int(p, 'Puesto') for p in positions))
    with repo.transaction() as c:
        repo.one(c, 'SELECT id FROM empresas WHERE id=%s FOR UPDATE', (empresa_id,))
        available = {r['id'] for r in repo.all_rows(c, 'SELECT id FROM puestos WHERE empresa_id=%s AND activo=1', (empresa_id,))}
        if not set(ids).issubset(available):
            raise CargaError('Seleccione puestos activos de esta empresa.')
        before = repo.all_rows(c, 'SELECT puesto_id FROM carga_puestos WHERE empresa_id=%s', (empresa_id,))
        c.execute('DELETE FROM carga_puestos WHERE empresa_id=%s', (empresa_id,))
        for puesto_id in ids:
            repo.insert(c, 'carga_puestos', dict(empresa_id=empresa_id, puesto_id=puesto_id))
        audit(c, empresa_id, user_id, 'puestos', None, before, ids)

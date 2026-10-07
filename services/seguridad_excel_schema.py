"""Formato editable de Seguridad e Higiene; validación independiente de Excel."""
import re
from datetime import date, datetime
from uuid import UUID

from services import seguridad_service as s

LEGACY_HEADERS = ['ID registro', 'Fila origen', 'Legajos', 'Persona de referencia', 'Tipo',
           'Fecha', 'Hora', 'Categoría', 'Descripción', 'Advertido', 'Lugar',
           'Clasificación', 'Atención', 'Lesión', 'Parte del cuerpo',
           'Enlaces originales', 'Revisión']
HEADERS = LEGACY_HEADERS + ['Tipo persona', 'IDs externos existentes', 'Nombre externo', 'Empresa externa']
BUSINESS = HEADERS[2:15] + HEADERS[18:]


def is_template(original):
    return original.get('formato') in ('seguridad_v1','seguridad_v2')


def values(original):
    return dict(zip(original['encabezados'], original['celdas']))


def parse(original, people, catalogs, external_people=()):
    from services.seguridad_import_service import key
    data = values(original)
    errors = []
    for field in HEADERS[:15]+HEADERS[17:]:
        if str(data.get(field) or '').startswith('='):
            errors.append(f'{field}: use un valor, no una fórmula.')
    try:
        identifier = str(UUID(str(data.get('ID registro') or '').strip()))
    except ValueError:
        identifier = ''
        errors.append('ID registro: falta un identificador válido. Use el de la plantilla.')
    raw_legajos = str(data.get('Legajos') or '').strip()
    person_type=key(data.get('Tipo persona')) if original.get('formato')=='seguridad_v2' else 'empleado'
    if person_type not in ('empleado','externo','mixto'):
        errors.append('Tipo persona: identifique si es empleado, externo o mixto; no se asigna automáticamente.')
    legajos = [v.strip() for v in raw_legajos.split(';') if v.strip()]
    ids = []
    for legajo in legajos:
        matches = [p for p in people if str(p['legajo']).strip() == legajo]
        if len(matches) != 1:
            errors.append(f'Legajos: {legajo} no identifica una persona única de esta empresa.')
        else:
            ids.append(matches[0]['id'])
    if not legajos and person_type in ('empleado','mixto'):
        errors.append('Legajos: seleccione al menos uno; separe varios con punto y coma.')
    if legajos and person_type=='externo':
        errors.append('Tipo persona: use mixto para informar sobre empleados y externos en el mismo evento.')
    if len(legajos) > 100 or len(set(legajos)) != len(legajos):
        errors.append('Legajos: máximo 100 personas, sin repetir.')
    external=[]
    known={p['id']:p for p in external_people if p['activo']}
    for external_token in str(data.get('IDs externos existentes') or '').split(';'):
        if not external_token.strip(): continue
        try:
            external_id=s.positive_int(external_token.strip(),'IDs externos existentes')
            if external_id not in known: raise s.Error('IDs externos existentes: persona inexistente, inactiva o de otra empresa.')
            external.append(dict(id=external_id))
        except s.Error as exc: errors.append(str(exc))
    external_name=str(data.get('Nombre externo') or '').strip()
    external_company=str(data.get('Empresa externa') or '').strip()
    if external_name or external_company:
        external.append(dict(nombre=external_name,empresa=external_company))
    if external and person_type=='empleado':
        errors.append('Tipo persona: use externo o mixto para incluir una persona externa.')
    if person_type in ('externo','mixto') and not external:
        errors.append('Nombre externo: obligatorio para una persona nueva, o seleccione un ID externo existente.')
    try: external=s.parse_externals(external)
    except s.Error as exc: errors.append('Nombre externo / empresa: '+str(exc))
    kind = key(data.get('Tipo'))
    if kind not in s.TIPOS:
        errors.append('Tipo: seleccione seguro, inseguro, accidente o incidente.')
    fecha = str(data.get('Fecha') or '').strip()
    try:
        if 'T' in fecha:
            fecha = datetime.fromisoformat(fecha).date().isoformat()
        parsed = date.fromisoformat(fecha)
        if parsed.year < 2000 or parsed > s.now_local().date():
            raise ValueError()
    except ValueError:
        errors.append('Fecha: use una fecha entre 2000 y hoy (AAAA-MM-DD).')
    hora = str(data.get('Hora') or '').strip()
    if re.fullmatch(r'\d{2}:\d{2}:00', hora):
        hora = hora[:5]
    if (hora and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hora)) or (kind in ('accidente', 'incidente') and not hora):
        errors.append('Hora: indique HH:MM; obligatoria en accidentes e incidentes.')
    category = str(data.get('Categoría') or '').strip()
    matches = [c for c in catalogs if c['clase'] == 'categoria' and c['activo']
               and c['tipo'] == kind and key(c['nombre']) == key(category)]
    cat = matches[0]['id'] if len(matches) == 1 else None
    if (category or kind in ('seguro', 'inseguro')) and cat is None:
        errors.append('Categoría: seleccione una categoría activa del tipo indicado.')
    description = str(data.get('Descripción') or '').strip()
    if not description or len(description) > 8000:
        errors.append('Descripción: obligatoria, máximo 8.000 caracteres.')
    details = {field: str(data.get(header) or '').strip() for field, header in
               zip(s.DETALLES, ['Advertido', 'Lugar', 'Clasificación', 'Atención', 'Lesión', 'Parte del cuerpo'])}
    details['advertido'] = key(details['advertido'])
    for field, value in details.items():
        if len(value) > 180:
            errors.append(f'{field}: máximo 180 caracteres.')
    if kind == 'inseguro' and details['advertido'] not in ('si', 'no'):
        errors.append('Advertido: indique si o no para un comportamiento inseguro.')
    if kind in ('accidente', 'incidente') and not details['lugar']:
        errors.append('Lugar: obligatorio en accidentes e incidentes.')
    result = dict(envio_id=identifier, tipo=kind, fecha_evento=fecha, hora_evento=hora,
                  categoria_id=cat, descripcion=description, involucrados=ids,
                  persona_original=str(data.get('Persona de referencia') or ''), **details)
    if external: result['externos']=external
    if not errors:
        try:
            s.parse(result)
        except s.Error as exc:
            errors.append(str(exc))
    return result, errors

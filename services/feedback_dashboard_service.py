import calendar
import datetime as dt
import unicodedata

from repositories.feedback_dashboard_repository import get_dashboard_data

MONTHS = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')


def branch_groups(branches):
    """Group aliases only inside their own company; retain original IDs in records."""
    groups = {}
    for branch in branches:
        name = ''.join(c for c in unicodedata.normalize('NFD', branch['nombre'].strip().lower()) if unicodedata.category(c) != 'Mn')
        alias = name in {'dolores', 'chascomus', 'dolores/chascomus', 'dolores / chascomus'}
        key = (branch.get('empresa_id'), 'dolores' if alias else int(branch['id']))
        if key not in groups:
            groups[key] = dict(branch, nombre='Dolores' if alias else branch['nombre'], ids=[])
        group = groups[key]
        group['ids'].append(int(branch['id']))
        if name == 'dolores':
            group['id'] = int(branch['id'])
        group['activa'] = bool(group.get('activa') or branch.get('activa'))
    return sorted(groups.values(), key=lambda g: (g.get('empresa_nombre') or '', g['nombre']))


def resolve_branch(groups, branch_id):
    if not branch_id:
        return None, None
    for group in groups:
        if branch_id in group['ids']:
            return group['id'], group['ids']
    return branch_id, []


def parse_period(args, *, default=False, today=None):
    today = today or dt.date.today()
    raw_start, raw_end = args.get('desde'), args.get('hasta')
    if not raw_start and not raw_end and not default:
        return None, None
    try:
        if raw_start or raw_end:
            start, end = dt.date.fromisoformat(raw_start or ''), dt.date.fromisoformat(raw_end or '')
        else:
            months = int(args.get('periodo') or 12)
            if months not in {1, 6, 12}:
                raise ValueError()
            offset = today.year * 12 + today.month - months
            start, end = dt.date(offset // 12, offset % 12 + 1, 1), today
        if start > end or end > today or (end - start).days > 1096:
            raise ValueError()
        return start, end
    except (TypeError, ValueError):
        raise ValueError('Elegí un período válido: desde y hasta, sin fechas futuras y de hasta tres años.') from None


def build_dashboard(*, desde, hasta, groups, sector_id=None, sucursal_ids=None, empleado_activo=None, blocked=False):
    data = dict(resumen={}, meses=[], sucursales=[], top_motivos=[], ranking=[]) if blocked else get_dashboard_data(
        desde=desde, hasta=hasta, sector_id=sector_id, sucursal_ids=sucursal_ids, empleado_activo=empleado_activo)
    summary = data['resumen']
    for key in ('total', 'resueltos', 'pendientes', 'vencidos', 'resueltos_en_sla', 'resueltos_fuera_sla', 'sin_plazo', 'empleados_con_carga'):
        summary.setdefault(key, 0)
    measured = summary['resueltos_en_sla'] + summary['resueltos_fuera_sla']
    summary['sla_pct'] = round(summary['resueltos_en_sla'] * 100 / measured, 1) if measured else None
    summary['sin_datos_sla'] = summary['resueltos'] - measured
    totals = {row['mes']: int(row['total']) for row in data.pop('meses')}
    months = []
    current = desde.replace(day=1)
    today = dt.date.today()
    while current <= hasta:
        last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
        months.append(dict(mes=current.strftime('%Y-%m'), label=f'{MONTHS[current.month-1]} {current.year}',
                           total=totals.get(current.strftime('%Y-%m'), 0),
                           desde=max(desde, current).isoformat(), hasta=min(hasta, last).isoformat(),
                           parcial=current < desde or last > hasta, actual=(current.year, current.month) == (today.year, today.month)))
        current = last + dt.timedelta(days=1)
    data['meses'] = months
    data['max_mes'] = max([1] + [row['total'] for row in months])
    lookup = {branch_id: group for group in groups for branch_id in group['ids']}
    grouped = {}
    for row in data['sucursales']:
        branch_id = row['sucursal_id']
        group = lookup.get(branch_id, dict(id=branch_id, nombre='Sin sucursal' if branch_id is None else f'Sucursal #{branch_id}', empresa_nombre=''))
        result = grouped.setdefault(group['id'], dict(id=group['id'], nombre=group['nombre'], empresa_nombre=group.get('empresa_nombre'), total=0, resueltos=0, vencidos=0))
        for field in ('total', 'resueltos', 'vencidos'):
            result[field] += int(row.get(field) or 0)
    data['sucursales'] = sorted(grouped.values(), key=lambda row: (-row['total'], row['nombre']))
    for row in data['sucursales']:
        row['resueltos_pct'] = round(row['resueltos'] * 100 / row['total'], 1) if row['total'] else 0
    return data

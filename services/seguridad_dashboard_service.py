"""Approved safety events, with distinct event and participation measures."""
from collections import Counter
from datetime import date
from services import seguridad_service as s


def streaks(dates, start, end):
    latest=max((d for d in dates if d<=end),default=None)
    if not start or start>end:
        return dict(actual=(end-latest).days if latest else None,record=None,ultimo=latest)
    days=sorted({d for d in dates if start<=d<=end})
    previous=start
    gaps=[]
    for day in days:
        gaps.append(max(0,(day-previous).days-(1 if previous in days else 0)))
        previous=day
    current=(end-previous).days
    return dict(actual=(end-latest).days if latest else current,record=max(gaps+[current]),ultimo=latest)


def configuration(empresa):
    with s.db.transaction(read_only=True) as c:
        row=s.db.one(c,'SELECT inicio FROM sh_dashboard_config WHERE empresa_id=%s',(empresa,))
    return row['inicio'] if row else None


def save_configuration(empresa,user,value):
    start=s.date_field(value)
    if start>s.now_local().date(): raise s.Error('El inicio del registro no puede ser futuro.')
    with s.db.transaction() as c:
        s.db.one(c,'SELECT id FROM empresas WHERE id=%s FOR UPDATE',(empresa,))
        before=s.db.one(c,'SELECT inicio FROM sh_dashboard_config WHERE empresa_id=%s',(empresa,))
        c.execute('''INSERT INTO sh_dashboard_config (empresa_id,inicio) VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE inicio=VALUES(inicio)''',(empresa,start))
        s.audit(c,empresa,user,'inicio_indicadores',dict(anterior=before,inicio=start))


def build(empresa,filters):
    today=s.now_local().date()
    start=s.date_field(filters.get('desde') or today.replace(month=1,day=1).isoformat())
    end=s.date_field(filters.get('hasta') or today.isoformat())
    if isinstance(start,str): start=date.fromisoformat(start)
    if isinstance(end,str): end=date.fromisoformat(end)
    if start>end or end>today or (end-start).days>3660:
        raise s.Error('Seleccione un período válido de hasta 10 años, sin fechas futuras.')
    view=filters.get('vista','inseguro')
    if view not in ('seguro','inseguro','indicadores','resumen'): raise s.Error('Vista inválida.')
    org={k:s.positive_int(filters[k],k) for k in ('sucursal_id','sector_id','puesto_id') if filters.get(k)}
    where="e.empresa_id=%s AND e.estado='aprobado'"
    args=[empresa]
    if org:
        where+=f' AND EXISTS(SELECT 1 FROM {s.CURRENT_PARTICIPANTS} p WHERE p.evento_id=e.id AND '+ ' AND '.join('p.'+k+'=%s' for k in org)+')'
        args+=list(org.values())
    period=where+' AND e.fecha_evento BETWEEN %s AND %s'
    params=tuple(args+[start,end])
    try: page=max(1,int(filters.get('page') or 1))
    except (ValueError,TypeError): raise s.Error('Página inválida.')
    with s.db.transaction(read_only=True) as c:
        annual_rows=s.db.all_rows(c,'''SELECT e.tipo,YEAR(e.fecha_evento) anio,MONTH(e.fecha_evento) mes,COUNT(*) cantidad
            FROM sh_eventos e WHERE '''+where+''' AND e.fecha_evento<=%s
            GROUP BY e.tipo,YEAR(e.fecha_evento),MONTH(e.fecha_evento)''',tuple(args+[end]))
        events=s.db.all_rows(c,'''SELECT e.id,e.tipo,e.fecha_evento,e.categoria_nombre
            FROM sh_eventos e WHERE '''+period+' ORDER BY e.fecha_evento DESC,e.id DESC',params)
        visible=[e for e in events if e['tipo']==view] if view in ('seguro','inseguro') else events
        page=min(page,max(1,(len(visible)+29)//30))
        items=visible[(page-1)*30:page*30]
        if items:
            marks=','.join(['%s']*len(items))
            details=s.db.all_rows(c,f'''SELECT e.id,e.descripcion,
                (SELECT COUNT(*) FROM sh_fotos f WHERE f.evento_id=e.id AND f.activo=1) fotos
                FROM sh_eventos e WHERE e.empresa_id=%s AND e.id IN ({marks})''',
                (empresa,*(e['id'] for e in items)))
            detail_by_id={e['id']:e for e in details}
            for event in items: event.update(detail_by_id.get(event['id'],{}))
        people=s.db.all_rows(c,f'''SELECT p.* FROM {s.CURRENT_PARTICIPANTS} p JOIN sh_eventos e ON e.id=p.evento_id WHERE '''+period,params)
        externals=s.db.all_rows(c,'''SELECT p.* FROM sh_evento_externos p JOIN sh_eventos e ON e.id=p.evento_id WHERE '''+period,params)
        options=s.db.all_rows(c,f'''SELECT DISTINCT p.sucursal_id,p.sucursal_nombre,p.sector_id,p.sector_nombre,p.puesto_id,p.puesto_nombre
            FROM {s.CURRENT_PARTICIPANTS} p JOIN sh_eventos e ON e.id=p.evento_id WHERE e.empresa_id=%s''',(empresa,))
        cfg=s.db.one(c,'''SELECT
            (SELECT inicio FROM sh_dashboard_config WHERE empresa_id=%s) inicio,
            (SELECT COUNT(*) FROM sh_import_filas f JOIN sh_importaciones i ON i.id=f.importacion_id
                WHERE i.empresa_id=%s AND f.evento_id IS NULL) unresolved''',(empresa,empresa))
        accident_where=where.replace("e.estado='aprobado'", "e.estado IN ('pendiente','aprobado')")
        participant_scope=(' AND '+' AND '.join('p.'+k+'=%s' for k in org)) if org else ''
        accident_dates=s.db.all_rows(c,f"SELECT DISTINCT e.fecha_evento,p.sucursal_id,p.sucursal_nombre FROM sh_eventos e LEFT JOIN {s.CURRENT_PARTICIPANTS} p ON p.evento_id=e.id WHERE "+accident_where+" AND e.tipo='accidente' AND e.fecha_evento<=%s"+participant_scope,
            tuple(args+[end]+list(org.values())))
        unresolved=cfg['unresolved']
    by_id={e['id']:e for e in events}
    for event in events: event['personas']=[]
    selected=[]
    for p in people:
        by_id[p['evento_id']]['personas'].append(dict(nombre=p['nombre'],referencia='Legajo '+p['legajo']))
        if all(p[k]==v for k,v in org.items()): selected.append(p)
    for p in externals:
        by_id[p['evento_id']]['personas'].append(dict(nombre=p['nombre'],referencia='Externo'))
    counts=Counter(e['tipo'] for e in events)
    visible_ids={e['id'] for e in visible}
    categories=Counter(e['categoria_nombre'] or 'Sin categoría' for e in visible)
    jobs=Counter(p['puesto_nombre'] or 'Sin puesto informado' for p in selected if p['evento_id'] in visible_ids)
    internal_counts=Counter(p['empleado_id'] for p in selected if p['evento_id'] in visible_ids)
    external_counts=Counter(p['externo_id'] for p in externals if p['evento_id'] in visible_ids and not org)
    internal_lookup={p['empleado_id']:p for p in reversed(selected)}
    external_lookup={p['externo_id']:p for p in reversed(externals)}
    ranking=[dict(id=i,nombre=internal_lookup[i]['nombre'],legajo=internal_lookup[i]['legajo'],cantidad=n) for i,n in internal_counts.most_common()]
    external_ranking=[dict(id=i,nombre=external_lookup[i]['nombre'],cantidad=n) for i,n in external_counts.most_common()]
    months={};current=start.replace(day=1)
    while current<=end:
        months[current.strftime('%Y-%m')]={k:0 for k in s.TIPOS}
        current=date(current.year+1,1,1) if current.month==12 else date(current.year,current.month+1,1)
    for e in events: months[e['fecha_evento'].strftime('%Y-%m')][e['tipo']]+=1
    years=list(range(min((r['anio'] for r in annual_rows),default=end.year),end.year+1))
    annual={kind:{year:[0 if date(year,month,1)<=end else None for month in range(1,13)] for year in years} for kind in s.TIPOS}
    for row in annual_rows:
        annual[row['tipo']][row['anio']][row['mes']-1]=row['cantidad']
    baseline=cfg['inicio'] if cfg else None
    branches={p['sucursal_id']:p['sucursal_nombre'] for p in options if p['sucursal_id'] and (not org.get('sucursal_id') or p['sucursal_id']==org['sucursal_id'])}
    branch_streaks=[dict(id=bid,nombre=name,**streaks([r['fecha_evento'] for r in accident_dates if r['sucursal_id']==bid],baseline,end)) for bid,name in sorted(branches.items(),key=lambda item:item[1] or '')]
    return dict(desde=start,hasta=end,vista=view,counts={k:counts[k] for k in s.TIPOS},total=len(events),
        categories=categories.most_common(),jobs=jobs.most_common(),job_total=sum(jobs.values()),ranking=ranking,
        external_ranking=external_ranking,months=months,annual=annual,years=years,items=items,page=page,
        visible_total=len(visible),inicio=baseline,streak=streaks([r['fecha_evento'] for r in accident_dates],baseline,end),branch_streaks=branch_streaks,
        options={k:sorted({(p[k],p[k.replace('_id','_nombre')] or 'Sin nombre') for p in options if p[k]},key=lambda x:x[1]) for k in ('sucursal_id','sector_id','puesto_id')},
        unresolved=unresolved,updated=s.now_local(),org=org)

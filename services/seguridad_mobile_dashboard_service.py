"""Employee-bound safety summaries; never accepts another employee's identity."""
from datetime import date,datetime
from services import seguridad_service as s
from services.seguridad_dashboard_service import streaks


def period(anio=None,mes=None):
    today=s.now_local().date()
    try:
        year=int(anio if anio is not None else today.year)
        month=int(mes) if mes not in (None,'') else None
        if not 2000<=year<=today.year or month is not None and not 1<=month<=12: raise ValueError()
    except (ValueError,TypeError): raise s.Error('Año o mes inválido.')
    start=date(year,month or 1,1)
    end=date(year+1,1,1) if month in (None,12) else date(year,month+1,1)
    return year,month,start,end


def indicators(employee,hasta=None):
    cutoff=s.date_field(hasta) if hasta else s.now_local().date()
    if cutoff>s.now_local().date() or cutoff.year<2000: raise s.Error('Fecha de corte inválida.')
    company=employee['empresa_id'];eid=employee['id'];branch=employee.get('sucursal_id')
    with s.db.transaction(read_only=True) as c:
        config=s.db.one(c,'SELECT inicio FROM sh_dashboard_config WHERE empresa_id=%s',(company,))
        start=config['inicio'] if config else None
        rows=s.db.all_rows(c,'''SELECT e.fecha_evento,
            EXISTS(SELECT 1 FROM sh_involucrados i WHERE i.evento_id=e.id AND i.empleado_id=%s) propio,
            EXISTS(SELECT 1 FROM sh_involucrados i WHERE i.evento_id=e.id AND i.sucursal_id=%s) sucursal
            FROM sh_eventos e WHERE e.empresa_id=%s AND e.estado IN ('pendiente','aprobado') AND e.tipo='accidente'
            AND e.fecha_evento<=%s''',(eid,branch,company,cutoff))
    entry=employee.get('fecha_ingreso')
    if isinstance(entry,datetime): entry=entry.date()
    elif entry and not isinstance(entry,date):
        try: entry=date.fromisoformat(str(entry)[:10])
        except ValueError: entry=None
    result={}
    for scope in ('empresa','sucursal','propio'):
        baseline=max(start,entry) if scope=='propio' and start and entry else start
        dates=[r['fecha_evento'] for r in rows if (scope=='empresa' or r[scope]) and (scope!='propio' or not entry or r['fecha_evento']>=entry)]
        reason='sin_sucursal' if scope=='sucursal' and not branch else None if dates else 'sin_inicio_configurado' if not baseline else 'corte_anterior_al_inicio' if baseline>cutoff else None
        values=streaks(dates,baseline,cutoff) if not reason else dict(actual=None,record=None,ultimo=None)
        result[scope]=dict(disponible=reason is None,motivo=reason,inicio=baseline,dias_sin_accidentes=values['actual'],
            record_dias_sin_accidentes=values['record'],ultimo_accidente=values['ultimo'],accidentes_registrados=len(dates) if not reason else None)
    return dict(hasta=cutoff,sucursal_id=branch,alcances=result,criterio='Último accidente por fecha del evento, pendiente o aprobado, de cada alcance; sucursal histórica de los involucrados. Rechazados y anulados excluidos. Sin accidentes se usa el inicio confiable, si existe; el récord requiere ese inicio.')


def summary(employee,anio=None,mes=None):
    year,month,start,end=period(anio,mes)
    today=s.now_local().date()
    with s.db.transaction() as c:
        rows=s.db.all_rows(c,'''SELECT YEAR(e.fecha_evento) anio,MONTH(e.fecha_evento) mes,e.tipo,COUNT(*) cantidad
            FROM sh_eventos e WHERE e.empresa_id=%s AND e.estado='aprobado' AND e.fecha_evento<=%s
            AND EXISTS(SELECT 1 FROM sh_involucrados i WHERE i.evento_id=e.id AND i.empleado_id=%s)
            GROUP BY YEAR(e.fecha_evento),MONTH(e.fecha_evento),e.tipo''',(employee['empresa_id'],today,employee['id']))
    years=list(range(min({r['anio'] for r in rows}|{year}),today.year+1))
    series={kind:[dict(anio=y,valores=[0 if date(y,m,1)<=today else None for m in range(1,13)]) for y in years] for kind in s.TIPOS}
    lookup={(kind,row['anio']):row['valores'] for kind,items in series.items() for row in items}
    counts={kind:0 for kind in s.TIPOS}
    for row in rows:
        lookup[row['tipo'],row['anio']][row['mes']-1]=row['cantidad']
        if row['anio']==year and (month is None or row['mes']==month): counts[row['tipo']]+=row['cantidad']
    return dict(anio=year,mes=month,fecha_corte=today,estado='aprobado',total=sum(counts.values()),por_tipo=counts,
        meses=list(range(1,13)),comparativo_anual=series,series_mensuales={kind:lookup[kind,year] for kind in s.TIPOS},
        indicadores=indicators(employee),actualizado_at=s.now_local())

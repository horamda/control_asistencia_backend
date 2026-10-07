"""Configurable recognition, distinct from incident reporting or blame."""
import hashlib
import json
from datetime import date,timedelta
from services import seguridad_service as s

GROUPS={'sucursal':'Por sucursal','puesto':'Por puesto','sucursal_puesto':'Por sucursal y puesto','empresa':'Toda la empresa'}
DEFAULTS=dict(puntos_seguro=1,puntos_inseguro=0,min_seguros=3,min_fechas=3,max_inseguros=0,agrupacion='sucursal',solo_activos=True)

def rules(c,company):
    row=s.db.one(c,'SELECT reglas,revision FROM sh_campeon_reglas WHERE empresa_id=%s',(company,))
    return (json.loads(row['reglas']),row['revision']) if row else (dict(DEFAULTS),0)

def integer(data,key,minimum,maximum):
    try:
        value=int(str(data.get(key,'')))
        if not minimum<=value<=maximum:raise ValueError()
        return value
    except (ValueError,TypeError):raise s.Error(f'{key}: indique un entero entre {minimum} y {maximum}.')

def save_rules(company,user,data):
    values={k:integer(data,k,low,high) for k,low,high in (
        ('puntos_seguro',1,1000),('puntos_inseguro',-1000,0),('min_seguros',1,10000),('min_fechas',1,366),('max_inseguros',0,10000))}
    values['agrupacion']=data.get('agrupacion')
    if values['agrupacion'] not in GROUPS:raise s.Error('Agrupación inválida.')
    active=str(data.get('solo_activos','0'))
    if active not in ('0','1'):raise s.Error('Seleccione el personal incluido.')
    values['solo_activos']=active=='1'
    revision=integer(data,'revision',0,2147483646)
    with s.db.transaction() as c:
        s.db.one(c,'SELECT id FROM empresas WHERE id=%s FOR UPDATE',(company,))
        before,current=rules(c,company)
        if revision!=current:raise s.Error('Las reglas cambiaron. Recargue antes de guardar.',409)
        c.execute('''INSERT INTO sh_campeon_reglas(empresa_id,reglas,revision,actualizado_at) VALUES(%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE reglas=VALUES(reglas),revision=VALUES(revision),actualizado_at=VALUES(actualizado_at)''',
            (company,s.dumps(values),current+1,s.now_local()))
        s.audit(c,company,user,'campeon_reglas',dict(anterior=before,nuevo=values,revision=current+1))

def period(year,month):
    today=s.now_local().date()
    year=integer({'anio':year},'anio',2000,today.year)
    month=integer({'mes':month or 0},'mes',0,12)
    start=date(year,month or 1,1)
    end=date(year+1,1,1) if month in (0,12) else date(year,month+1,1)
    if start>today:raise s.Error('El período no puede ser futuro.')
    return year,month,start,end

def calculate(c,company,year,month):
    year,month,start,end=period(year,month)
    config,revision=rules(c,company)
    people=s.employees(c,company,active=config['solo_activos'])
    rows=s.db.all_rows(c,'''SELECT p.empleado_id,
        COUNT(CASE WHEN e.tipo='seguro' THEN 1 END) seguros,
        COUNT(CASE WHEN e.tipo='inseguro' THEN 1 END) inseguros,
        COUNT(DISTINCT CASE WHEN e.tipo='seguro' THEN e.fecha_evento END) fechas
        FROM sh_eventos e JOIN sh_involucrados p ON p.evento_id=e.id
        WHERE e.empresa_id=%s AND e.estado='aprobado' AND e.tipo IN ('seguro','inseguro')
        AND e.fecha_evento>=%s AND e.fecha_evento<%s AND e.fecha_evento<=%s GROUP BY p.empleado_id''',
        (company,start,end,s.now_local().date()))
    totals={r['empleado_id']:r for r in rows}
    groups={}
    for person in people:
        row={**person,**totals.get(person['id'],dict(seguros=0,inseguros=0,fechas=0))}
        row['puntaje']=row['seguros']*config['puntos_seguro']+row['inseguros']*config['puntos_inseguro']
        reasons=[]
        if row['seguros']<config['min_seguros']:reasons.append(f"Requiere {config['min_seguros']} seguros")
        if row['fechas']<config['min_fechas']:reasons.append(f"Requiere {config['min_fechas']} fechas distintas con seguros")
        if row['inseguros']>config['max_inseguros']:reasons.append(f"Supera {config['max_inseguros']} inseguros permitidos")
        row['motivos']=reasons;row['elegible']=not reasons
        mode=config['agrupacion']
        keys=['sucursal'] if mode=='sucursal' else ['puesto'] if mode=='puesto' else ['sucursal','puesto'] if mode=='sucursal_puesto' else []
        key=':'.join(str(row[k+'_id'] or 0) for k in keys) or 'empresa'
        name=' · '.join(row[k+'_nombre'] or 'Sin '+k for k in keys) or 'Toda la empresa'
        group=groups.setdefault(key,dict(key=key,nombre=name,personas=[]))
        group['personas'].append(row)
    for group in groups.values():
        group['personas'].sort(key=lambda p:(not p['elegible'],-p['puntaje'],p['apellido'] or '',p['nombre'] or '',p['id']))
        eligible=[p for p in group['personas'] if p['elegible']]
        group['ganadores']=[p for p in eligible if p['puntaje']==eligible[0]['puntaje']] if eligible else []
        # Bind confirmation to the displayed rules, eligibility, people and scores.
        group['firma']=hashlib.sha256(s.dumps(dict(company=company,year=year,month=month,reglas=config,revision=revision,grupo=group)).encode()).hexdigest()
    awards=s.db.all_rows(c,'''SELECT id,grupo,agrupacion,resultado,confirmado_at FROM sh_campeon_premios
        WHERE empresa_id=%s AND anio=%s AND mes=%s ORDER BY id''',(company,year,month))
    awards=[{**a,'resultado':json.loads(a['resultado'])} for a in awards]
    award_map={a['grupo']:a for a in awards if a['agrupacion']==config['agrupacion']}
    for group in groups.values():group['premio']=award_map.get(group['key'])
    return dict(reglas=config,revision=revision,anio=year,mes=month,desde=start,hasta=min(end-timedelta(days=1),s.now_local().date()),
        cerrado=end<=s.now_local().date(),grupos=sorted(groups.values(),key=lambda g:g['nombre']),premios=awards)

def build(company,year,month=None):
    with s.db.transaction(read_only=True) as c:return calculate(c,company,year,month)

def confirm(company,user,data):
    with s.db.transaction() as c:
        s.db.one(c,'SELECT id FROM empresas WHERE id=%s FOR UPDATE',(company,))
        result=calculate(c,company,data.get('anio'),data.get('mes'))
        if not result['cerrado']:raise s.Error('El período sigue abierto. El resultado es provisional.')
        group=next((g for g in result['grupos'] if g['key']==str(data.get('grupo'))),None)
        if not group or group['firma']!=data.get('firma'):raise s.Error('El resultado cambió. Recargue y revise antes de confirmar.',409)
        if group['premio']:raise s.Error('Este grupo ya tiene un reconocimiento confirmado.',409)
        if not group['ganadores']:raise s.Error('No hay candidatos que cumplan las reglas.')
        snapshot=dict(reglas=result['reglas'],revision=result['revision'],grupo=group['nombre'],ganadores=group['ganadores'])
        award=s.db.insert(c,'sh_campeon_premios',dict(empresa_id=company,anio=result['anio'],mes=result['mes'],
            agrupacion=result['reglas']['agrupacion'],grupo=group['key'],resultado=s.dumps(snapshot),usuario_id=user,confirmado_at=s.now_local()))
        s.audit(c,company,user,'campeon_confirmado',dict(premio_id=award,**snapshot))

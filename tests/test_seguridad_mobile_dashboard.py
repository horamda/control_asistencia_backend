from services import seguridad_service as s,seguridad_dashboard_service as d,seguridad_mobile_dashboard_service as mobile
from tests.test_seguridad import database,client,payload,employee
from tests.test_seguridad_dashboard import config_table,approved

HEADERS={'Authorization':'Bearer 10'}


def test_personal_summary_types_series_and_no_other_identity(client):
    approved(involucrados=[10,11],fecha_evento='2025-02-01')
    approved(involucrados=[10],fecha_evento='2026-09-01')
    approved(involucrados=[11],tipo='inseguro',categoria_id=2,advertido='no')
    s.create(1,payload(involucrados=[10]),user=99)
    result=client.get('/api/v1/mobile/seguridad/resumen?anio=2026&mes=9&empleado_id=11',headers=HEADERS)
    assert result.status_code==200
    data=result.json
    assert data['total']==1 and data['por_tipo']==dict(seguro=1,inseguro=0,accidente=0,incidente=0)
    assert data['series_mensuales']['seguro']==[0,0,0,0,0,0,0,0,1,0,None,None]
    assert data['comparativo_anual']['seguro'][0]['anio']==2025
    assert data['comparativo_anual']['seguro'][0]['valores'][1]==1
    assert data['indicadores']['alcances']['propio']['motivo']=='sin_inicio_configurado'
    assert 'descripcion' not in data
    history=client.get('/api/v1/mobile/seguridad/eventos?tipo=inseguro&empleado_id=11',headers=HEADERS).json
    assert history['total']==0


def test_indicator_scopes_distinct_events_privacy_and_hire_date(client):
    d.save_configuration(1,99,'2026-09-01')
    approved(tipo='accidente',categoria_id=None,hora_evento='10:00',lugar='Lugar',fecha_evento='2026-09-05',involucrados=[10,11])
    approved(tipo='accidente',categoria_id=None,hora_evento='10:00',lugar='Lugar',fecha_evento='2026-09-10',involucrados=[12])
    approved(tipo='incidente',categoria_id=None,hora_evento='10:00',lugar='Lugar',fecha_evento='2026-09-14',involucrados=[10])
    response=client.get('/api/v1/mobile/seguridad/indicadores?hasta=2026-09-15&sucursal_id=2',headers=HEADERS)
    assert response.status_code==200
    result=response.json
    assert result['sucursal_id']==1
    assert result['alcances']['empresa']['dias_sin_accidentes']==5
    assert result['alcances']['sucursal']['dias_sin_accidentes']==10
    assert result['alcances']['propio']['dias_sin_accidentes']==10
    assert result['alcances']['sucursal']['accidentes_registrados']==1
    assert 'descripcion' not in response.get_data(as_text=True) and 'empleado_id' not in response.get_data(as_text=True)
    newer={**employee(),'fecha_ingreso':'2026-09-12','sucursal_id':None}
    own=mobile.indicators(newer,'2026-09-15')
    assert own['alcances']['propio']['dias_sin_accidentes']==3
    assert own['alcances']['sucursal']['motivo']=='sin_sucursal'


def test_ranking_branch_own_position_and_no_accident_rank(client):
    approved(involucrados=[10])
    approved(involucrados=[12])
    result=client.get('/api/v1/mobile/seguridad/ranking?anio=2026&alcance=sucursal&sucursal_id=2',headers=HEADERS).json
    assert result['sucursal_id']==1
    assert [r['empleado_id'] for r in result['rankings']['seguro']]==[10]
    assert result['mi_posicion']['seguro']['posicion']==1 and result['mi_posicion']['inseguro'] is None
    assert set(result['rankings'])=={'seguro','inseguro'}
    assert result['rankings_externos']=={'seguro':[],'inseguro':[]}


def test_auth_parameters_and_capabilities(client):
    for path in ('resumen','indicadores'):
        assert client.get('/api/v1/mobile/seguridad/'+path).status_code==401
    for path in ('resumen?anio=2099','resumen?mes=13','indicadores?hasta=2099-01-01','ranking?alcance=otra'):
        assert client.get('/api/v1/mobile/seguridad/'+path,headers=HEADERS).status_code==400
    config=client.get('/api/v1/mobile/seguridad/config',headers=HEADERS).json
    assert config['dashboard']['version_contrato']=='1.33.2'
    assert config['dashboard']['ranking_alcances']==['empresa','sucursal']


def test_latest_pending_accident_by_branch_without_configuration(client):
    from datetime import date
    def accident(day,people):
        return s.create(1,payload(tipo='accidente',categoria_id=None,hora_evento='10:00',lugar='Deposito',fecha_evento=day,involucrados=people),user=99)[0]
    accident('2026-08-06',[10,11])
    accident('2026-09-01',[12])
    rejected=accident('2026-09-20',[10])
    s.review(1,rejected,99,'rechazado',1,'No corresponde')
    annulled=accident('2026-09-21',[10])
    s.review(1,annulled,99,'anulado',1,'Duplicado')
    result=mobile.indicators(employee(),'2026-10-02')
    branch=result['alcances']['sucursal']
    assert branch['disponible'] and branch['dias_sin_accidentes']==57
    assert branch['ultimo_accidente']==date(2026,8,6)
    assert branch['record_dias_sin_accidentes'] is None
    assert branch['accidentes_registrados']==1
    web=d.build(1,dict(desde='2026-10-01',hasta='2026-10-02',vista='indicadores'))
    assert {r['id']:r['actual'] for r in web['branch_streaks']}=={1:57,2:31}
    scoped=d.build(1,dict(hasta='2026-10-02',vista='indicadores',sucursal_id=1))
    assert scoped['streak']['actual']==57
    assert scoped['total']==0
    with s.db.transaction() as c:
        c.execute('UPDATE empleados SET sucursal_id=2 WHERE id IN (10,11)')
    # Both web and mobile use current assignments, without changing old reports.
    moved=mobile.indicators(employee(),'2026-10-02')
    assert moved['sucursal_id']==2
    assert moved['alcances']['sucursal']['dias_sin_accidentes']==31
    empty=mobile.indicators(employee(13),'2026-10-02')
    assert empty['alcances']['sucursal']['dias_sin_accidentes'] is None
    assert d.build(1,dict(hasta='2026-10-02',vista='indicadores',sucursal_id=2))['streak']['actual']==31

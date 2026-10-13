"""Supplementary plans and business-rule checks; SELECT/EXPLAIN only."""
import datetime as dt
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from db import _load_db_settings
import mysql.connector


def main():
    s=_load_db_settings()
    c=mysql.connector.connect(host=s['host'],port=int(s['port']),user=s['user'],password=s['password'],database=s['db'],connection_timeout=15,read_timeout=20,collation='utf8mb4_general_ci')
    cur=c.cursor(dictionary=True)
    cur.execute('SET SESSION MAX_EXECUTION_TIME=5000')
    data={'started_utc':str(dt.datetime.now(dt.timezone.utc)),'queries':{}}
    path=Path(__file__).resolve().parents[1]/'output/db_audit_plans_20261013.json'
    def q(name,sql):
        start=time.perf_counter()
        try:
            c.start_transaction(readonly=True)
            cur.execute(sql)
            rows=cur.fetchall()
            data['queries'][name]={'sql':sql,'rows':rows,'elapsed_ms':round((time.perf_counter()-start)*1000,2)}
        except mysql.connector.Error as e:
            data['queries'][name]={'sql':sql,'error_code':e.errno,'error':str(e)}
        finally:
            c.rollback()
            path.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    checks={
      'tls_session':"SHOW SESSION STATUS LIKE 'Ssl_cipher'",
      'server_clock':"SELECT NOW() server_now,UTC_TIMESTAMP() utc_now,@@system_time_zone system_zone",
      'justification_ranges':"SELECT COUNT(*) total,SUM(fecha_desde IS NULL) missing_start,SUM(fecha_hasta IS NULL) missing_end,SUM(fecha IS NULL AND fecha_desde IS NULL) undated FROM justificaciones",
      'justification_states':"SELECT estado,COUNT(*) total FROM justificaciones GROUP BY estado",
      'attendance_states':"SELECT estado,COUNT(*) total FROM asistencias GROUP BY estado",
      'mark_domains':"SELECT accion,tipo_marca,metodo,COUNT(*) total FROM asistencia_marcas GROUP BY accion,tipo_marca,metodo",
      'attendance_future':"SELECT COUNT(*) future_rows FROM asistencias WHERE fecha>DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)",
      'marks_future':"SELECT COUNT(*) future_rows FROM asistencia_marcas WHERE fecha>DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)",
      'mobile_freshness':"SELECT COUNT(*) total,MIN(fecha_login) first_login,MAX(fecha_ultimo_request) last_request FROM mobile_sesiones",
      'attendance_missing_pair':"SELECT COUNT(*) total,SUM(hora_entrada IS NULL AND hora_salida IS NOT NULL) exit_without_entry,SUM(hora_entrada IS NOT NULL AND hora_salida IS NULL) entry_without_exit,SUM(hora_salida<hora_entrada) reversed_times FROM asistencias WHERE fecha<DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)",
      'assignment_overlap':"SELECT COUNT(*) overlapping_pairs FROM empleado_horarios a JOIN empleado_horarios b ON a.empleado_id=b.empleado_id AND a.id<b.id AND a.fecha_desde<=COALESCE(b.fecha_hasta,'9999-12-31') AND b.fecha_desde<=COALESCE(a.fecha_hasta,'9999-12-31')",
      'employee_org_scope':"SELECT COUNT(*) total,SUM(s.empresa_id<>e.empresa_id) branch_mismatches,SUM(sec.empresa_id<>e.empresa_id) sector_mismatches,SUM(p.empresa_id<>e.empresa_id) position_mismatches FROM empleados e LEFT JOIN sucursales s ON s.id=e.sucursal_id LEFT JOIN sectores sec ON sec.id=e.sector_id LEFT JOIN puestos p ON p.id=e.puesto_id",
      'required_employee_fields':"SELECT COUNT(*) total,SUM(TRIM(COALESCE(nombre,''))='') missing_name,SUM(TRIM(COALESCE(apellido,''))='') missing_surname,SUM(TRIM(COALESCE(dni,''))='') missing_dni,SUM(TRIM(COALESCE(legajo,''))='') missing_employee_number,SUM(activo=1 AND sucursal_id IS NULL) active_without_branch,SUM(activo=1 AND sector_id IS NULL) active_without_sector FROM empleados",
      'view_presence':"SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA=DATABASE()",
    }
    plans={
      'monthly_marks':"SELECT am.id,am.empleado_id,am.fecha,am.hora,am.accion FROM asistencia_marcas_reporte am JOIN empleados e ON e.id=am.empleado_id WHERE am.empresa_id=1 AND am.fecha BETWEEN '2026-10-01' AND '2026-10-31' ORDER BY am.fecha,am.hora,am.id",
      'justification_overlap':"SELECT j.empleado_id,j.fecha_desde,j.fecha_hasta FROM justificaciones j JOIN empleados e ON e.id=j.empleado_id WHERE j.estado='aprobada' AND e.empresa_id=1 AND COALESCE(j.fecha_hasta,j.fecha)>='2026-10-01' AND COALESCE(j.fecha_desde,j.fecha)<='2026-10-31'",
      'safety_page':"SELECT id,tipo,fecha_evento FROM sh_eventos WHERE empresa_id=1 AND estado='aprobado' AND fecha_evento BETWEEN '2026-01-01' AND '2026-10-13' AND tipo='seguro' ORDER BY fecha_evento DESC,id DESC LIMIT 30",
      'vacation_approved':"SELECT empleado_id,fecha_desde,fecha_hasta FROM vacaciones_movimientos WHERE empresa_id=1 AND tipo='tomado' AND estado='aprobado' AND fecha_desde<='2026-10-31' AND fecha_hasta>='2026-10-01' AND revertido_por_movimiento_id IS NULL AND origen_movimiento_id IS NULL",
      'attendance_page':"SELECT id,empleado_id,fecha FROM asistencias WHERE empresa_id=1 AND fecha BETWEEN '2026-10-01' AND '2026-10-31' ORDER BY fecha DESC,id DESC LIMIT 50",
    }
    try:
        for name,sql in checks.items(): q(name,sql)
        for name,sql in plans.items(): q('explain:'+name,'EXPLAIN '+sql)
        for n in range(5): q('roundtrip:'+str(n),'SELECT 1 AS ok')
        # Composite FKs must be checked as a whole, not as independent columns.
        meta=json.loads((path.parent/'db_audit_20261013.json').read_text(encoding='utf-8'))
        grouped={}
        for fk in meta['queries']['foreign_keys']['rows']:
            grouped.setdefault((fk['TABLE_NAME'],fk['CONSTRAINT_NAME']),[]).append(fk)
        for (table,name),rows in grouped.items():
            if len(rows)<2: continue
            join=' AND '.join(f"c.`{r['COLUMN_NAME']}`=p.`{r['REFERENCED_COLUMN_NAME']}`" for r in rows)
            nonnull=' AND '.join(f"c.`{r['COLUMN_NAME']}` IS NOT NULL" for r in rows)
            q('composite_fk:'+table+':'+name,f"SELECT COUNT(*) orphan_rows FROM `{table}` c LEFT JOIN `{rows[0]['REFERENCED_TABLE_NAME']}` p ON {join} WHERE {nonnull} AND p.`{rows[0]['REFERENCED_COLUMN_NAME']}` IS NULL")
        data['finished_utc']=str(dt.datetime.now(dt.timezone.utc))
        path.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        print(json.dumps({'queries':len(data['queries']),'errors':[k for k,v in data['queries'].items() if 'error' in v]}))
    finally: cur.close();c.close()


if __name__=='__main__':main()

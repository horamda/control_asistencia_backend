"""Measure selected reads and remove only verified identical nonunique indexes.

Default is read-only. --apply executes the reviewed online DDL, saving reversal SQL.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import _load_db_settings
import mysql.connector

PAIRS = [
    ('empleado_excepciones', 'idx_ee_empresa_fecha', 'idx_ex_emp_empresa_fecha'),
    ('empleado_horarios', 'idx_empleado_horarios_vigente', 'idx_eh_actual'),
    ('empleado_horarios', 'idx_empleado_fechas', 'idx_eh_empleado_rango'),
]


def signature(rows):
    return [(r['Column_name'], r['Sub_part'], r['Collation'], r['Index_type'], r.get('Visible'), r.get('Expression'), r['Non_unique']) for r in sorted(rows, key=lambda r: r['Seq_in_index'])]


def validate_pair(indexes, drop, keep):
    if drop not in indexes or keep not in indexes or signature(indexes[drop]) != signature(indexes[keep]):
        raise ValueError(f'Index definitions differ or are absent: {drop}, {keep}')
    if not indexes[drop] or any(r['Non_unique'] != 1 or not r['Column_name'] or r['Sub_part'] or r.get('Expression') is not None for r in indexes[drop]):
        raise ValueError(f'Not a supported redundant nonunique index: {drop}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    s = _load_db_settings()
    conn = mysql.connector.connect(host=s['host'], port=int(s['port']), user=s['user'], password=s['password'], database=s['db'], connection_timeout=15, read_timeout=30, autocommit=True, collation='utf8mb4_general_ci')
    cur = conn.cursor(dictionary=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = ROOT / 'output' / f'index_optimization_{stamp}.json'
    data = {'started_utc': stamp, 'apply': args.apply, 'changes': [], 'measurements': {}}
    def save():
        path.write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')
    def indexes(table):
        cur.execute(f'SHOW INDEX FROM `{table}`')
        grouped = {}
        for row in cur.fetchall():
            grouped.setdefault(row['Key_name'], []).append(row)
        return grouped
    try:
        cur.execute('SET SESSION MAX_EXECUTION_TIME=5000')
        cur.execute('SET SESSION lock_wait_timeout=5')
        source = json.loads((ROOT / 'output/db_audit_plans_20261013.json').read_text(encoding='utf-8'))
        queries = {k: v['sql'].removeprefix('EXPLAIN ') for k, v in source['queries'].items() if k.startswith('explain:')}
        queries.update({
            'schedule': "SELECT empleado_id,fecha_desde,fecha_hasta FROM empleado_horarios WHERE empleado_id=1 AND fecha_desde<='2026-10-31' AND (fecha_hasta IS NULL OR fecha_hasta>='2026-10-01')",
            'exceptions': "SELECT fecha FROM empleado_excepciones WHERE empresa_id=1 AND fecha BETWEEN '2026-10-01' AND '2026-10-31'",
            'mobile_recent': 'SELECT id,empleado_id,fecha_login FROM mobile_sesiones ORDER BY fecha_login DESC LIMIT 50',
        })
        for table, drop, keep in PAIRS:
            idx = indexes(table)
            if drop not in idx:
                data['changes'].append({'table': table, 'drop': drop, 'status': 'already_absent'})
                continue
            validate_pair(idx, drop, keep)
            cols = ', '.join('`' + r['Column_name'] + '`' + (' DESC' if r['Collation'] == 'D' else '') for r in idx[drop])
            data['changes'].append({'table': table, 'drop': drop, 'keep': keep, 'definition': signature(idx[drop]), 'sql': f'ALTER TABLE `{table}` DROP INDEX `{drop}`, ALGORITHM=INPLACE, LOCK=NONE', 'rollback_sql': f'ALTER TABLE `{table}` ADD INDEX `{drop}` ({cols}), ALGORITHM=INPLACE, LOCK=NONE', 'status': 'verified'})
        for phase in ['before', 'after'] if args.apply else ['before']:
            if phase == 'after':
                save()
                for change in data['changes']:
                    if change['status'] != 'verified':
                        continue
                    # Recheck immediately before each independent DDL; no FK is disabled.
                    idx = indexes(change['table'])
                    validate_pair(idx, change['drop'], change['keep'])
                    cur.execute(change['sql'])
                    change['status'] = 'applied'
                    save()
                    idx = indexes(change['table'])
                    if change['drop'] in idx or change['keep'] not in idx:
                        raise RuntimeError('Post-DDL verification failed')
            measured = {}
            data['measurements'][phase] = measured
            for name, sql in queries.items():
                start = time.perf_counter()
                cur.execute('EXPLAIN ANALYZE ' + sql)
                measured[name] = {'sql': sql, 'plan': cur.fetchall(), 'client_ms': round((time.perf_counter()-start)*1000, 2)}
                save()
        data['finished_utc'] = str(dt.datetime.now(dt.timezone.utc))
        save()
        print(str(path))
        print(json.dumps(data['changes'], default=str))
    finally:
        save()
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()

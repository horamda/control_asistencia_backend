"""Remove only verified exact duplicate non-unique indexes; dry run by default."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db

CANDIDATES = (
    ('asistencias', 'idx_asis_empleado_fecha', 'idx_asistencias_empleado_fecha'),
    ('asistencias', 'idx_asis_empresa_fecha', 'idx_asistencias_empresa_fecha'),
    ('legajo_eventos', 'fk_legajo_eventos_justificacion', 'idx_legajo_eventos_justificacion'),
)


def signature(rows):
    return [(r['NON_UNIQUE'], r['SEQ_IN_INDEX'], r['COLUMN_NAME'], r['COLLATION'],
             r['SUB_PART'], r['INDEX_TYPE'], r['IS_VISIBLE'], r.get('EXPRESSION')) for r in rows]


def verify_pair(drop, keep):
    if not keep:
        raise ValueError('Retained index is missing')
    if not drop:
        return False
    if any(r['NON_UNIQUE'] != 1 or r['INDEX_TYPE'] != 'BTREE' or r['IS_VISIBLE'] != 'YES'
           or r['SUB_PART'] is not None or r.get('EXPRESSION') for r in drop + keep):
        raise ValueError('Only full-column visible non-unique BTREE indexes are supported')
    if signature(drop) != signature(keep):
        raise ValueError('Indexes are not exact duplicates')
    return True


def indexes(cursor, table):
    cursor.execute('SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,COLLATION,SUB_PART,INDEX_TYPE,IS_VISIBLE,EXPRESSION FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX', (table,))
    result = {}
    for row in cursor.fetchall():
        result.setdefault(row['INDEX_NAME'], []).append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_file = args.report_dir / 'result.json'
    if report_file.exists():
        raise SystemExit('Use a fresh report directory to preserve previous evidence.')
    init_orm()
    db = get_db()
    c = db.cursor(dictionary=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'apply': args.apply, 'tables': {}, 'operations': []}
    def save():
        report_file.write_text(json.dumps(report, default=str, indent=2), encoding='utf-8')
    try:
        c.execute('SET SESSION lock_wait_timeout=5')
        c.execute('SELECT VERSION() AS version')
        report['server'] = c.fetchone()
        rollback = []
        for table, drop, keep in CANDIDATES:
            if table not in report['tables']:
                c.execute(f'SHOW CREATE TABLE `{table}`')
                report['tables'][table] = {'ddl': c.fetchone(), 'indexes': indexes(c, table)}
            current = report['tables'][table]['indexes']
            needed = verify_pair(current.get(drop, []), current.get(keep, []))
            op = {'table': table, 'drop': drop, 'keep': keep, 'status': 'planned' if needed else 'already_absent'}
            report['operations'].append(op)
            if needed:
                columns = ','.join('`'+r['COLUMN_NAME']+'`'+(' DESC' if r['COLLATION']=='D' else '') for r in current[drop])
                rollback.append(f'ALTER TABLE `{table}` ADD INDEX `{drop}` ({columns}), ALGORITHM=INPLACE, LOCK=NONE;')
        (args.report_dir / 'rollback.sql').write_text('-- Run only for indexes actually removed; see result.json.\nSET SESSION lock_wait_timeout=5;\n'+'\n'.join(rollback)+'\n', encoding='utf-8')
        save()
        for op in report['operations']:
            if op['status'] != 'planned' or not args.apply:
                continue
            current = indexes(c, op['table'])
            if not verify_pair(current.get(op['drop'], []), current.get(op['keep'], [])):
                op['status'] = 'already_absent'; save(); continue
            # Do not fall back to a blocking table rebuild. DDL auto-commits per operation.
            c.execute(f"ALTER TABLE `{op['table']}` DROP INDEX `{op['drop']}`, ALGORITHM=INPLACE, LOCK=NONE")
            op['status'] = 'removed'; save()
            after = indexes(c, op['table'])
            assert op['drop'] not in after and signature(after[op['keep']]) == signature(current[op['keep']])
            op['verified'] = True; save()
        report['completed_at'] = datetime.now(timezone.utc).isoformat(); save()
        print(json.dumps(report['operations'], indent=2))
    except Exception as exc:
        report['error_type'] = type(exc).__name__; save()
        raise
    finally:
        c.close(); db.close()

if __name__ == '__main__':
    main()

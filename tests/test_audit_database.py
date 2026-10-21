"""New regression checks use the same disposable MariaDB fixture as safety."""
import re
from pathlib import Path

from tests.test_seguridad import database


def test_bootstrap_version_runs_once(database, monkeypatch):
    from scripts import bootstrap_schema as migration
    calls = []
    monkeypatch.setattr(migration, 'init_db', lambda: None)
    monkeypatch.setattr(migration, 'get_db', database)
    monkeypatch.setattr(migration, 'bootstrap_schema', lambda: calls.append('migration'))
    # Las versiones posteriores a la que se prueba no tienen que ver con este control y usan tablas que esta base
    # minima no tiene (el esquema real viene del volcado de produccion): se marcan como ya aplicadas.
    versiones = re.findall(r"version = '([0-9a-z_]+)'", Path(migration.__file__).read_text(encoding='utf-8'))
    posteriores = versiones[versiones.index('20261014_epp_concepts') + 1:]
    db = database()
    cur = db.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS app_schema_versions (version VARCHAR(100) PRIMARY KEY, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.executemany('INSERT INTO app_schema_versions(version) VALUES (%s)', [(v,) for v in posteriores])
    db.commit()
    cur.close()
    db.close()
    migration.main()
    db = database()
    cur = db.cursor()
    cur.execute("INSERT INTO epp_conceptos_reposicion(empresa_id,nombre) VALUES(1,'Desgaste')")
    db.commit()
    cur.close()
    db.close()
    migration.main()
    assert calls == ['migration']
    db = database()
    cur = db.cursor()
    try:
        cur.execute("SELECT nombre FROM epp_conceptos_reposicion WHERE empresa_id=1")
        assert cur.fetchall() == [('Desgaste',)]
        cur.execute("SELECT concepto_reposicion_id,concepto_reposicion FROM epp_pedidos")
        assert cur.fetchall() == []
        cur.execute("SELECT COUNT(*) FROM app_schema_versions WHERE version='20261014_epp_concepts'")
        assert cur.fetchone()[0] == 1
    finally:
        cur.close()
        db.close()


def test_trivia_batch_deduplicates_in_database(database, monkeypatch):
    from repositories import trivia_repository as repo
    db = database()
    cur = db.cursor()
    try:
        cur.execute('CREATE TABLE trivia_notificaciones (trivia_id INT, empleado_id INT, empleado_dni VARCHAR(30), tipo VARCHAR(30), mensaje TEXT, UNIQUE(trivia_id,empleado_id,tipo))')
        db.commit()
        monkeypatch.setattr(repo, 'get_db', database)
        rows = [dict(trivia_id=1, empleado_id=i, empleado_dni=str(i), tipo='recordatorio_2h', mensaje='recordatorio') for i in range(1001)]
        repo.save_notificaciones_batch(rows)
        repo.save_notificaciones_batch(rows)
        cur.execute('SELECT COUNT(*) FROM trivia_notificaciones')
        assert cur.fetchone()[0] == 1001
    finally:
        cur.close()
        db.close()


def test_monthly_justifications_are_scoped_and_not_truncated(database, monkeypatch):
    from repositories import attendance_report_repository as repo
    db = database()
    cur = db.cursor()
    try:
        cur.execute('CREATE TABLE justificaciones (empleado_id INT, fecha DATE, fecha_desde DATE, fecha_hasta DATE, estado VARCHAR(20))')
        cur.executemany('INSERT INTO justificaciones VALUES (%s,%s,NULL,NULL,%s)', [(10, '2026-09-01', 'aprobada')] * 20001 + [(20, '2026-09-01', 'aprobada'), (11, '2026-09-01', 'pendiente')])
        db.commit()
        monkeypatch.setattr(repo, 'get_db', database)
        rows = repo.approved_justifications(fecha_desde='2026-09-01', fecha_hasta='2026-09-30', empresa_id=1, sucursal_id=1, sector_id=1)
        assert len(rows) == 20001
        assert {r['empleado_id'] for r in rows} == {10}
    finally:
        cur.close()
        db.close()

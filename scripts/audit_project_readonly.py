"""Local audit: syntax, inventory and synthetic probes. No database connections.

Run from the repository root with venv/Scripts/python.exe scripts/audit_project_readonly.py.
Writes only output/audit_20261013_evidence.json; does not initialize the real app.
"""
import ast
from collections import Counter
from datetime import date
from io import BytesIO
import importlib.metadata
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['FLASK_SKIP_APP_BOOT'] = '1'
os.environ['APP_ENV'] = 'test'


def inventory():
    files = [p for directory in ('web', 'routes', 'services', 'repositories', 'utils', 'models', 'tests')
             for p in (ROOT / directory).rglob('*.py')]
    files += [ROOT / name for name in ('app.py', 'db.py', 'extensions.py', 'config.py')]
    errors, routes, module_counts = [], [], Counter()
    for path in files:
        source = path.read_text(encoding='utf-8-sig')
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(dict(file=str(path.relative_to(ROOT)), line=exc.lineno, error=exc.msg))
            continue
        module_counts[path.relative_to(ROOT).parts[0]] += 1
        if path.relative_to(ROOT).parts[0] == 'tests':
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                verb = dec.func.attr
                if verb not in ('route', 'get', 'post', 'put', 'patch', 'delete'):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                methods = [verb.upper()] if verb != 'route' else ['GET']
                for kw in dec.keywords:
                    if kw.arg == 'methods':
                        methods = ast.literal_eval(kw.value)
                routes.append(dict(file=path.relative_to(ROOT).as_posix(), line=dec.lineno,
                                   function=node.name, path=dec.args[0].value, methods=methods))
    mutations = [r for r in routes if 'GET' in r['methods'] and r['function'] in ('activar', 'desactivar')]
    return dict(python_files=len(files), by_directory=dict(module_counts), syntax_errors=errors,
                route_declarations=len(routes), route_files=len({r['file'] for r in routes}),
                get_activation_routes=mutations, routes=routes)


def probes():
    # Block DB use even if a future code change adds an unexpected read.
    import extensions
    import db
    with patch.object(extensions, 'get_db', side_effect=AssertionError('DB disabled for audit')), \
         patch.object(db, 'get_raw_connection', side_effect=AssertionError('DB disabled for audit')):
        from flask import Flask
        from flask_wtf.csrf import CSRFProtect
        import web.auth.decorators as auth
        import web.empleados.empleados_routes as employees
        from services.asistencia_monthly_report_service import build_monthly_attendance_report as build
        from services.table_export_service import build_table_export
        from openpyxl import load_workbook

        app = Flask('isolated_audit')
        app.secret_key = 'audit-only-synthetic-session-secret'
        CSRFProtect(app)
        app.register_blueprint(employees.empleados_bp)
        changes = []
        reader = dict(id=99, activo=1, rol='consulta', empresa_id=1)
        with patch.object(auth, 'get_web_user_by_id', return_value=reader), \
             patch.object(auth, 'get_user_permissions', return_value={'empleados': {'ver': True}}), \
             patch.object(employees, 'set_activo', side_effect=lambda *args: changes.append(args)), \
             patch.object(employees, 'log_audit', return_value=None):
            client = app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = 99
            response = client.get('/empleados/desactivar/123')
        permission_probe = dict(status=response.status_code, simulated_mutations=changes,
                                user_permissions={'empleados': {'ver': True}}, csrf_enabled=True)

        employee = dict(id=1, nombre='Persona', apellido='Prueba', activo=1)
        future = build(year=2026, month=11, empleados=[employee], marcas=[], justificaciones=[])
        marks = [dict(id=i, empleado_id=1, fecha='2026-10-05', hora=hour, accion=action)
                 for i, (hour, action) in enumerate([
                     ('08:00', 'ingreso'), ('12:00', 'egreso'), ('16:00', 'ingreso'), ('20:00', 'egreso')], 1)]
        split = build(year=2026, month=10, empleados=[employee], marcas=marks, justificaciones=[])
        xlsx = build_table_export('Synthetic audit', [{'texto': '=1+1'}], 'xlsx')
        workbook = load_workbook(BytesIO(xlsx.data), data_only=False)
        formula = workbook.active['A4']
        result = dict(read_only_user_get_mutation=permission_probe,
                      future_month={'context_date': '2026-10-13', 'month': '2026-11', 'kpis': future['kpis']},
                      split_shift={'expected_hours': 8, 'reported_hours': split['kpis']['horas_trabajadas']},
                      excel_text={'input': '=1+1', 'stored_type': formula.data_type, 'stored_value': formula.value})
        timings = []
        for count in (100, 500, 1000):
            staff = [dict(employee, id=i) for i in range(1, count + 1)]
            marks = [dict(id=i * 100 + day * 2 + index, empleado_id=i,
                          fecha=f'2026-09-{day:02}', hora=hour, accion=action)
                     for i in range(1, count + 1) for day in range(1, 27)
                     for index, (hour, action) in enumerate([('08:00', 'ingreso'), ('16:00', 'egreso')])]
            samples = []
            for _ in range(3):
                start = time.perf_counter()
                build(year=2026, month=9, empleados=staff, marcas=marks, justificaciones=[])
                samples.append(round((time.perf_counter() - start) * 1000, 2))
            timings.append(dict(employees=count, marks=len(marks), samples_ms=samples,
                                median_ms=statistics.median(samples)))
        result['synthetic_cpu_benchmark'] = timings
        return result


if __name__ == '__main__':
    result = dict(date='2026-10-13', scope='Local source and synthetic data only',
                  python=sys.version, packages={name: importlib.metadata.version(name)
                  for name in ('Flask', 'Werkzeug', 'SQLAlchemy', 'pytest', 'openpyxl')},
                  inventory=inventory(), probes=probes())
    target = ROOT / (sys.argv[1] if len(sys.argv) > 1 else 'output/audit_20261013_evidence.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({**result, 'inventory': {k: v for k, v in result['inventory'].items() if k != 'routes'}},
                     ensure_ascii=True, indent=2))

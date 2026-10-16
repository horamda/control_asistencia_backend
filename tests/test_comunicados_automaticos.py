"""Historial de avisos automaticos en Comunicados (sin MySQL)."""
import datetime as dt
from contextlib import contextmanager

import pytest

from services import comunicado_service as s

WHO = {"empresa_id": 1, "user_id": 9}
HOY = dt.datetime(2026, 10, 16, 12, 0)


@pytest.fixture
def base(monkeypatch):
    consultas = []
    filas = [
        {"id": 3, "tipo": "salida_pendiente", "titulo": "¿Te olvidaste de fichar la salida?", "cuerpo": "…",
         "estado": "reintentar", "error": "503", "creado_at": HOY, "enviado_at": None, "empleado_id": 10,
         "apellido": "Perez", "nombre": "Ana", "legajo": "10"},
        {"id": 2, "tipo": "epp_resuelto", "titulo": "EPP aprobado", "cuerpo": "…", "estado": "enviado", "error": None,
         "creado_at": HOY, "enviado_at": HOY, "empleado_id": 11, "apellido": None, "nombre": None, "legajo": None},
    ]

    @contextmanager
    def transaction(read_only=False):
        assert read_only
        yield None

    def all_rows(c, sql, args):
        consultas.append((" ".join(sql.split()), args))
        assert sql.count("%s") == len(args)
        if "GROUP BY p.estado" in sql:
            return [{"estado": "enviado", "n": 5}, {"estado": "reintentar", "n": 1}, {"estado": "enviando", "n": 2},
                    {"estado": "sin_dispositivo", "n": 4}]
        return [dict(f) for f in filas]

    def one(c, sql, args):
        consultas.append((" ".join(sql.split()), args))
        assert sql.count("%s") == len(args)
        return {"n": 2}

    monkeypatch.setattr(s.db, "transaction", transaction)
    monkeypatch.setattr(s.db, "all_rows", all_rows)
    monkeypatch.setattr(s.db, "one", one)
    monkeypatch.setattr(s, "now_local", lambda: HOY)
    return consultas


def test_por_defecto_ultimos_30_dias_sin_comunicados_ni_pruebas(base):
    resultado = s.automaticos(WHO, {})
    sql, args = base[0]
    assert resultado["filtros"]["desde"] == "2026-09-17" and resultado["filtros"]["hasta"] == "2026-10-16"
    assert args[:3] == (1, dt.date(2026, 9, 17), dt.date(2026, 10, 17))
    assert "comunicado" not in args and "prueba" not in args
    assert set(args[3:]) == set(s.TIPOS_AUTOMATICOS)


def test_resumen_agrupa_la_cola_como_en_cola(base):
    resultado = s.automaticos(WHO, {})
    assert resultado["resumen"] == {"enviado": 5, "sin_dispositivo": 4, "error": 0, "pendiente": 3}


def test_items_con_nombre_de_tipo_y_estado_normalizado(base):
    items = s.automaticos(WHO, {})["items"]
    assert items[0]["tipo_nombre"] == "Salida sin fichar"
    assert items[0]["estado"] == "pendiente"
    assert items[1]["estado"] == "enviado"


def test_filtros_de_tipo_estado_empleado_y_pagina(base):
    resultado = s.automaticos(WHO, {"tipo": "epp_resuelto", "estado": "pendiente", "q": "perez",
                                    "desde": "2026-10-10", "hasta": "2026-10-01", "page": "2"})
    assert resultado["filtros"] == {"tipo": "epp_resuelto", "estado": "pendiente", "q": "perez",
                                    "desde": "2026-10-01", "hasta": "2026-10-10"}
    sql_items, args_items = base[-1]
    assert "p.tipo IN (%s)" in sql_items and "e.apellido LIKE %s" in sql_items
    assert "p.estado IN (%s, %s, %s)" in sql_items
    assert args_items[-2:] == (s.HISTORIAL_POR_PAGINA, s.HISTORIAL_POR_PAGINA)
    # El resumen por estado no aplica el filtro de estado.
    assert "p.estado IN" not in base[0][0]


def test_valores_desconocidos_se_ignoran(base):
    resultado = s.automaticos(WHO, {"tipo": "comunicado", "estado": "x", "page": "abc", "desde": "nada"})
    assert resultado["filtros"]["tipo"] == "" and resultado["filtros"]["estado"] == ""
    assert resultado["page"] == 1


def test_pantalla_de_avisos_automaticos(monkeypatch, base):
    import app as app_module
    import web.auth.decorators as auth_decorators
    import web.comunicados.routes as rutas

    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 9
    usuario = {"id": 9, "empresa_id": 1, "activo": 1, "rol": "admin"}
    monkeypatch.setattr(auth_decorators, "can_access_module", lambda *a, **k: True)
    monkeypatch.setattr(auth_decorators, "has_role", lambda *a, **k: True)
    monkeypatch.setattr(auth_decorators, "_cached_web_user", lambda user_id: usuario)
    monkeypatch.setattr(rutas, "_cached_web_user", lambda user_id: usuario)

    resp = client.get("/comunicados/automaticos?estado=enviado")

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200, html[:500]
    assert "Avisos automáticos" in html
    assert "¿Te olvidaste de fichar la salida?" in html
    assert "Empleado #11" in html
    assert '<option value="enviado" selected>' in html

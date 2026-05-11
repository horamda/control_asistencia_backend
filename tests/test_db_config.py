import pytest

import db


def test_build_uri_rejects_placeholder_db_user(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USER", "usuario_db")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "asistencias")

    with pytest.raises(db.DatabaseConfigError, match="DB_USER"):
        db._build_uri()


def test_build_uri_rejects_placeholder_db_name(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USER", "root")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "nombre_db")

    with pytest.raises(db.DatabaseConfigError, match="DB_NAME"):
        db._build_uri()


def test_build_uri_accepts_railway_mysql_env_aliases(monkeypatch):
    for name in ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MYSQLHOST", "mysql.railway.internal")
    monkeypatch.setenv("MYSQLPORT", "3306")
    monkeypatch.setenv("MYSQLUSER", "railway")
    monkeypatch.setenv("MYSQLPASSWORD", "secret with spaces")
    monkeypatch.setenv("MYSQLDATABASE", "railway")

    uri = db._build_uri()

    assert uri == (
        "mysql+mysqlconnector://railway:secret+with+spaces"
        "@mysql.railway.internal:3306/railway"
    )


def test_get_raw_connection_wraps_mysql_access_denied(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USER", "root")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "asistencias")

    class FakeAccessDenied(Exception):
        errno = 1045

    class FakeEngine:
        def raw_connection(self):
            raise FakeAccessDenied("Access denied for user 'root'@'localhost'")

    monkeypatch.setattr(db, "get_engine", lambda: FakeEngine())

    with pytest.raises(db.DatabaseConfigError, match="No se pudo conectar a MySQL"):
        db.get_raw_connection()


def test_get_raw_connection_wraps_mysql_connectivity_error(monkeypatch):
    monkeypatch.setenv("DB_HOST", "190.210.132.63")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_USER", "root")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "asistencias")

    class FakeConnectivityError(Exception):
        errno = 2003

    class FakeEngine:
        def raw_connection(self):
            raise FakeConnectivityError("Can't connect to MySQL server")

    monkeypatch.setattr(db, "get_engine", lambda: FakeEngine())

    with pytest.raises(db.DatabaseConfigError, match="No se pudo abrir la conexion MySQL"):
        db.get_raw_connection()

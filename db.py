import os
from contextlib import contextmanager
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

load_dotenv("/etc/secrets/.env", override=False)
load_dotenv(override=False)

Base = declarative_base()
engine = None
SessionLocal = None
_PLACEHOLDER_ENV_VALUES = {
    "DB_USER": {"usuario_db"},
    "DB_NAME": {"nombre_db"},
}


class DatabaseConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise DatabaseConfigError(f"{name} no configurada")
    return value


def _validate_env_value(name: str, value: str) -> None:
    if value in _PLACEHOLDER_ENV_VALUES.get(name, set()):
        raise DatabaseConfigError(
            f"{name} tiene un valor de plantilla ({value!r}) en .env. "
            "Reemplazalo por la credencial real de MySQL antes de iniciar la app."
        )


def _load_db_settings() -> dict[str, str]:
    host = _require_env("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = _require_env("DB_USER")
    password = os.getenv("DB_PASSWORD") or ""
    db = _require_env("DB_NAME")
    _validate_env_value("DB_USER", user)
    _validate_env_value("DB_NAME", db)
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "db": db,
    }


def _build_uri():
    settings = _load_db_settings()
    safe_pw = quote_plus(settings["password"])
    return (
        f"mysql+mysqlconnector://{settings['user']}:{safe_pw}"
        f"@{settings['host']}:{settings['port']}/{settings['db']}"
    )


def _current_db_target() -> str:
    settings = _load_db_settings()
    return f"{settings['user']}@{settings['host']}:{settings['port']}/{settings['db']}"


def _is_mysql_access_denied(exc: Exception) -> bool:
    if getattr(exc, "errno", None) == 1045:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "errno", None) == 1045:
        return True
    return "Access denied for user" in str(exc)


def _is_mysql_connectivity_error(exc: Exception) -> bool:
    if getattr(exc, "errno", None) in {2003, 2005}:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "errno", None) in {2003, 2005}:
        return True
    return False


def _build_access_denied_message() -> str:
    return (
        f"No se pudo conectar a MySQL ({_current_db_target()}). "
        "MySQL rechazo las credenciales indicadas. "
        "Revisa DB_USER, DB_PASSWORD, DB_NAME y los permisos de ese usuario."
    )


def _build_connectivity_message() -> str:
    return (
        f"No se pudo abrir la conexion MySQL hacia {_current_db_target()}. "
        "Verifica que el host y puerto sean correctos, que el servidor permita conexiones remotas "
        "desde esta maquina y que no haya un firewall bloqueando el acceso."
    )


def init_orm():
    global engine, SessionLocal
    if engine is not None and SessionLocal is not None:
        return
    engine = create_engine(
        _build_uri(),
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600"))
    )
    SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


def get_engine():
    if engine is None:
        raise RuntimeError("ORM no inicializado")
    return engine


def get_session():
    if SessionLocal is None:
        raise RuntimeError("ORM no inicializado")
    return SessionLocal()


@contextmanager
def session_scope():
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_raw_connection():
    try:
        return get_engine().raw_connection()
    except Exception as exc:
        if _is_mysql_access_denied(exc):
            raise DatabaseConfigError(_build_access_denied_message()) from exc
        if _is_mysql_connectivity_error(exc):
            raise DatabaseConfigError(_build_connectivity_message()) from exc
        raise

import os
from contextlib import contextmanager
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

load_dotenv()

Base = declarative_base()
engine = None
SessionLocal = None


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} no configurada")
    return value


def _build_uri():
    user = _require_env("DB_USER")
    password = os.getenv("DB_PASSWORD") or ""
    host = _require_env("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    db = _require_env("DB_NAME")
    safe_pw = quote_plus(password)
    return f"mysql+mysqlconnector://{user}:{safe_pw}@{host}:{port}/{db}"


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
    return get_engine().raw_connection()

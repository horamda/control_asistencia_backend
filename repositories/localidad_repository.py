from db import get_session
from models.localidad import Localidad


def get_all():
    session = get_session()
    try:
        rows = session.query(Localidad).order_by(Localidad.provincia, Localidad.localidad).all()
        return [r.__dict__ | {"codigo_postal": r.codigo_postal} for r in rows]
    finally:
        session.close()


def get_by_codigo(codigo_postal: str):
    session = get_session()
    try:
        row = session.query(Localidad).filter_by(codigo_postal=codigo_postal).first()
        return row.__dict__ if row else None
    finally:
        session.close()


def exists_codigo(codigo_postal: str):
    session = get_session()
    try:
        return session.query(Localidad).filter_by(codigo_postal=codigo_postal).first() is not None
    finally:
        session.close()


def create(data: dict):
    session = get_session()
    try:
        loc = Localidad(
            codigo_postal=data.get("codigo_postal"),
            localidad=data.get("localidad"),
            provincia=data.get("provincia"),
            pais=data.get("pais")
        )
        session.add(loc)
        session.commit()
        return True
    finally:
        session.close()


def update(codigo_postal: str, data: dict):
    session = get_session()
    try:
        row = session.query(Localidad).filter_by(codigo_postal=codigo_postal).first()
        if not row:
            return False
        row.localidad = data.get("localidad")
        row.provincia = data.get("provincia")
        row.pais = data.get("pais")
        session.commit()
        return True
    finally:
        session.close()


def delete(codigo_postal: str):
    session = get_session()
    try:
        row = session.query(Localidad).filter_by(codigo_postal=codigo_postal).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True
    finally:
        session.close()

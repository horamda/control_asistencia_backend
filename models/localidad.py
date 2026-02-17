from sqlalchemy import Column, String, TIMESTAMP, text
from db import Base


class Localidad(Base):
    __tablename__ = "localidades"

    codigo_postal = Column(String(10), primary_key=True)
    localidad = Column(String(100), nullable=False)
    provincia = Column(String(100), nullable=False)
    pais = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

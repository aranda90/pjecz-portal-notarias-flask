"""
Modulos
"""

from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import relationship

from lib.universal_mixin import UniversalMixin
from portal_notarias.extensions import database


class Modulo(database.Model, UniversalMixin):
    """Modulo"""

    # Nombre de la tabla
    __tablename__ = "modulos"

    # Clave primaria
    id = Column(Integer, primary_key=True)

    # Columnas
    nombre = Column(String(256), unique=True, nullable=False)
    nombre_corto = Column(String(64), nullable=False)
    icono = Column(String(48), nullable=False)
    ruta = Column(String(64), nullable=False)
    en_navegacion = Column(Boolean, nullable=False, default=True)
    en_plataforma_carina = Column(Boolean, nullable=False, default=False)
    en_plataforma_hercules = Column(Boolean, nullable=False, default=False)
    en_plataforma_web = Column(Boolean, nullable=False, default=False)
    en_portal_notarias = Column(Boolean, nullable=False, default=False)

    # Hijos
    bitacoras = relationship("Bitacora", back_populates="modulo")
    permisos = relationship("Permiso", back_populates="modulo")

    def __repr__(self):
        """Representación"""
        return f"<Modulo {self.nombre}>"

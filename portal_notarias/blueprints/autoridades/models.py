"""
Autoridad
"""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.universal_mixin import UniversalMixin
from portal_notarias.extensions import database


class Autoridad(database.Model, UniversalMixin):
    """Autoridad"""

    # Nombre de la tabla
    __tablename__ = "autoridades"

    # Clave primaria
    id = Column(Integer, primary_key=True)

    # Claves foráneas
    distrito_id = Column(Integer, ForeignKey("distritos.id"), index=True, nullable=False)
    distrito = relationship("Distrito", back_populates="autoridades")
    municipio_id = Column(Integer, ForeignKey("municipios.id"), index=True, nullable=False)
    municipio = relationship("Municipio", back_populates="autoridades")

    # Columnas
    clave = Column(String(16), nullable=False, unique=True)
    descripcion = Column(String(256), nullable=False)
    descripcion_corta = Column(String(64), nullable=False)
    es_archivo_solicitante = Column(Boolean, nullable=False, default=False)
    es_cemasc = Column(Boolean, nullable=False, default=False)
    es_defensoria = Column(Boolean, nullable=False, default=False)
    es_extinto = Column(Boolean, nullable=False, default=False)
    es_jurisdiccional = Column(Boolean, nullable=False, default=False)
    es_notaria = Column(Boolean, nullable=False, default=False)
    es_organo_especializado = Column(Boolean, nullable=False, default=False)
    es_revisor_escrituras = Column(Boolean, nullable=False, default=False)
    directorio_edictos = Column(String(256), nullable=False, default="", server_default="")

    # Hijos
    usuarios = relationship("Usuario", back_populates="autoridad")
    edictos = relationship("Edicto", back_populates="autoridad", lazy="noload")

    def __repr__(self):
        """Representación"""
        return f"<Autoridad {self.clave}>"

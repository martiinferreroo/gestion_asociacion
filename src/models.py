from datetime import date, datetime

from database import Base
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    rol = Column(String, default="gestor")  # 'admin' o 'gestor'
    activo = Column(Integer, default=1)


class Socio(Base):
    __tablename__ = "socios"

    num_socio = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String, nullable=False)
    apellidos = Column(String, nullable=False)
    # Sin unique: varios socios pueden tener el DNI provisional. La unicidad
    # de los DNI reales se comprueba en el código.
    dni = Column(String, nullable=False, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    # date.today (sin paréntesis): se evalúa en cada alta, no al arrancar.
    fecha_alta = Column(Date, default=date.today)
    # Al día, Pendiente, Baja (automática), Baja (manual), Inactivo
    estado = Column(String, default="Inactivo")
    notas = Column(Text, nullable=True)

    cuotas = relationship(
        "Cuota", back_populates="socio", cascade="all, delete-orphan"
    )
    historial = relationship("HistorialSocio", back_populates="socio")


class Cuota(Base):
    __tablename__ = "cuotas"

    id_cuota = Column(String, primary_key=True)  # Formato: ARM-CUO2026-001
    num_socio = Column(Integer, ForeignKey("socios.num_socio"), nullable=False)
    fecha_pago = Column(DateTime, default=datetime.now)
    forma_pago = Column(String, nullable=False)
    importe = Column(Float, default=0.0)
    # Los recibos no se borran: se anulan, conservando su número.
    anulada = Column(Integer, default=0)
    fecha_anulacion = Column(DateTime, nullable=True)
    motivo_anulacion = Column(String, nullable=True)

    socio = relationship("Socio", back_populates="cuotas")


class HistorialSocio(Base):
    __tablename__ = "historial_socios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    num_socio = Column(Integer, ForeignKey("socios.num_socio"), nullable=False)
    fecha_registro = Column(DateTime, default=datetime.now)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    accion = Column(String, nullable=False)
    detalles = Column(Text, nullable=True)

    socio = relationship("Socio", back_populates="historial")
    usuario = relationship("Usuario")


class Configuracion(Base):
    __tablename__ = "configuracion"

    id = Column(Integer, primary_key=True, default=1)
    nombre_asociacion = Column(String, default="")
    cif = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    importe_cuota_defecto = Column(Float, default=10.0)
    logo_url = Column(String, nullable=True)
    color_primario = Column(String, nullable=True)  # botones y enlaces
    color_cabecera = Column(String, nullable=True)  # barra superior

    # Copias de seguridad automáticas
    backup_activo = Column(Integer, default=0)
    backup_frecuencia = Column(String, default="diaria")  # diaria, cada_n_dias, semanal, mensual
    backup_cada_dias = Column(Integer, default=1)
    backup_dia_semana = Column(Integer, default=0)        # 0 = lunes
    backup_dia_mes = Column(Integer, default=1)
    backup_hora = Column(String, default="03:00")
    backup_conservar = Column(Integer, default=14)        # nº de copias que se guardan
    backup_desde = Column(DateTime, nullable=True)        # cuándo se activó o cambió el horario
    backup_ultimo = Column(DateTime, nullable=True)       # última copia automática correcta
    backup_ultimo_estado = Column(String, nullable=True)


class AgendaNota(Base):
    __tablename__ = "agenda_notas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)      # día al que se refiere la nota
    creada = Column(DateTime, default=datetime.now)       # cuándo se escribió
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    texto = Column(Text, nullable=False)

    usuario = relationship("Usuario")

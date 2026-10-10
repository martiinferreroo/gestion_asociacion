"""Copias de seguridad automáticas de la base de datos (sin dependencias de la web)."""
import calendar
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

PATRON = re.compile(r"^asociacion_\d{4}-\d{2}-\d{2}_\d{6}\.db$")

FRECUENCIAS = [
    ("diaria", "Todos los días"),
    ("cada_n_dias", "Cada varios días"),
    ("semanal", "Una vez a la semana"),
    ("mensual", "Una vez al mes"),
]
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
HORA_POR_DEFECTO = time(3, 0)


@dataclass
class Programa:
    activo: bool = False
    frecuencia: str = "diaria"
    cada_dias: int = 1
    dia_semana: int = 0          # 0 = lunes
    dia_mes: int = 1
    hora: str = "03:00"
    desde: Optional[datetime] = None     # cuándo se activó o se cambió el horario
    ultimo: Optional[datetime] = None    # última copia automática correcta


def parsear_hora(texto) -> Optional[time]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (texto or "").strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def proxima(p: Programa, ahora: datetime) -> Optional[datetime]:
    """Momento de la siguiente copia programada (None si está desactivada).

    Se cuenta desde la última copia correcta o, si aún no hay ninguna, desde que
    se activó o cambió el horario. Si el servidor estuvo apagado a la hora
    prevista, la copia se hace al arrancar (una sola, no una por cada hueco).
    """
    if not p.activo:
        return None
    ref = p.ultimo or p.desde or ahora
    hora = parsear_hora(p.hora) or HORA_POR_DEFECTO

    if p.frecuencia in ("diaria", "cada_n_dias"):
        n = 1 if p.frecuencia == "diaria" else max(1, int(p.cada_dias or 1))
        return datetime.combine(ref.date() + timedelta(days=n), hora)

    if p.frecuencia == "semanal":
        for i in range(8):
            c = datetime.combine(ref.date() + timedelta(days=i), hora)
            if c.weekday() == int(p.dia_semana) and c > ref:
                return c

    if p.frecuencia == "mensual":
        anio, mes = ref.year, ref.month
        for _ in range(3):
            dia = min(max(1, int(p.dia_mes)), calendar.monthrange(anio, mes)[1])
            c = datetime.combine(date(anio, mes, dia), hora)
            if c > ref:
                return c
            anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)

    return None


def toca(p: Programa, ahora: datetime) -> bool:
    siguiente = proxima(p, ahora)
    return siguiente is not None and siguiente <= ahora


def describir(p: Programa) -> str:
    hora = (parsear_hora(p.hora) or HORA_POR_DEFECTO).strftime("%H:%M")
    if p.frecuencia == "diaria":
        return f"todos los días a las {hora}"
    if p.frecuencia == "cada_n_dias":
        n = max(1, int(p.cada_dias or 1))
        return f"cada {n} días a las {hora}" if n > 1 else f"todos los días a las {hora}"
    if p.frecuencia == "semanal":
        return f"los {DIAS_SEMANA[int(p.dia_semana) % 7]} a las {hora}"
    return f"el día {int(p.dia_mes)} de cada mes a las {hora}"


def crear_copia(ruta_db: Path, carpeta: Path, ahora: Optional[datetime] = None) -> Path:
    """Copia la base de datos en caliente (API de backup de SQLite)."""
    ahora = ahora or datetime.now()
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"asociacion_{ahora:%Y-%m-%d_%H%M%S}.db"
    temporal = destino.with_name(destino.name + ".tmp")
    origen = sqlite3.connect(ruta_db)
    copia = sqlite3.connect(temporal)
    try:
        with copia:
            origen.backup(copia)
    finally:
        origen.close()
        copia.close()
    temporal.replace(destino)     # el archivo aparece completo o no aparece
    return destino


def listar(carpeta: Path, limite: Optional[int] = None):
    """Copias existentes, de la más reciente a la más antigua."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    salida = []
    for f in sorted((f for f in carpeta.iterdir() if PATRON.match(f.name)), reverse=True):
        info = f.stat()
        salida.append({
            "nombre": f.name, "bytes": info.st_size,
            "fecha": datetime.fromtimestamp(info.st_mtime),
        })
    return salida[:limite] if limite else salida


def podar(carpeta: Path, conservar: int) -> int:
    """Borra las más antiguas y deja las `conservar` más recientes."""
    conservar = max(1, int(conservar or 1))
    borradas = 0
    for viejo in listar(carpeta)[conservar:]:
        (Path(carpeta) / viejo["nombre"]).unlink(missing_ok=True)
        borradas += 1
    return borradas

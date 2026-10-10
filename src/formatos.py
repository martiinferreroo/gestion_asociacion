"""Formato de fechas e importes para las plantillas (sin dependencias de la web)."""
from datetime import datetime


def fecha(value, formato="%d/%m/%Y"):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(formato)


def fechahora(value):
    return fecha(value, "%d/%m/%Y %H:%M")


def euros(value):
    numero = f"{(value or 0):,.2f}"
    return numero.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(value):
    """Martes, 29 de septiembre de 2026 (sin depender del idioma del sistema)."""
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    texto = f"{_DIAS[value.weekday()]}, {value.day} de {_MESES[value.month - 1]} de {value.year}"
    return texto[0].upper() + texto[1:]


def tamano(bytes_):
    """Tamaño legible: 845 B, 12,3 KB, 4,5 MB."""
    n = float(bytes_ or 0)
    for unidad in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidad == "GB":
            texto = f"{n:.0f}" if unidad == "B" else f"{n:.1f}".replace(".", ",")
            return f"{texto} {unidad}"
        n /= 1024

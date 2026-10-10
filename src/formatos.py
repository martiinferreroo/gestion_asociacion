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

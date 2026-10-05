"""Cambios de esquema que SQLAlchemy no aplica solo a una base ya existente."""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

COLUMNAS_SOCIOS = [
    "num_socio", "nombre", "apellidos", "dni", "fecha_nacimiento", "telefono",
    "email", "direccion", "fecha_alta", "estado", "notas",
]

# Igual que la tabla original, pero sin UNIQUE en dni: varios socios pueden
# compartir el DNI provisional. La unicidad de los DNI reales se controla
# por código.
NUEVA_TABLA = """
CREATE TABLE socios_nueva (
    num_socio INTEGER NOT NULL,
    nombre VARCHAR NOT NULL,
    apellidos VARCHAR NOT NULL,
    dni VARCHAR NOT NULL,
    fecha_nacimiento DATE,
    telefono VARCHAR,
    email VARCHAR,
    direccion VARCHAR,
    fecha_alta DATE,
    estado VARCHAR,
    notas TEXT,
    PRIMARY KEY (num_socio)
)
"""


def _dni_es_unico(con) -> bool:
    for fila in con.execute("PRAGMA index_list(socios)").fetchall():
        nombre, unico = fila[1], fila[2]
        if unico:
            columnas = [c[2] for c in con.execute(f'PRAGMA index_info("{nombre}")')]
            if columnas == ["dni"]:
                return True
    return False


def quitar_unicidad_dni(ruta_db: Path) -> bool:
    """Reconstruye la tabla socios sin UNIQUE en dni. Devuelve True si migró."""
    ruta_db = Path(ruta_db)
    if not ruta_db.exists():
        return False

    con = sqlite3.connect(ruta_db)
    try:
        hay_tabla = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='socios'"
        ).fetchone()
        if not hay_tabla or not _dni_es_unico(con):
            return False
    finally:
        con.close()

    # Copia de seguridad previa, por si algo saliera mal.
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(ruta_db, ruta_db.with_name(f"{ruta_db.stem}_antes_de_migrar_{marca}.db"))

    con = sqlite3.connect(ruta_db, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN")
        try:
            existentes = [r[1] for r in con.execute("PRAGMA table_info(socios)")]
            comunes = ", ".join(c for c in COLUMNAS_SOCIOS if c in existentes)
            con.execute(NUEVA_TABLA)
            con.execute(f"INSERT INTO socios_nueva ({comunes}) SELECT {comunes} FROM socios")
            con.execute("DROP TABLE socios")
            con.execute("ALTER TABLE socios_nueva RENAME TO socios")
            con.execute("CREATE INDEX IF NOT EXISTS ix_socios_dni ON socios (dni)")
            if con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("La migración dejaría referencias rotas; cancelada.")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
        con.close()
    return True

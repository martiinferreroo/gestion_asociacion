import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
import migraciones

ESQUEMA_ANTIGUO = """
CREATE TABLE socios (
 num_socio INTEGER NOT NULL, nombre VARCHAR NOT NULL, apellidos VARCHAR NOT NULL, dni VARCHAR NOT NULL,
 fecha_nacimiento DATE, telefono VARCHAR, email VARCHAR, direccion VARCHAR, fecha_alta DATE, estado VARCHAR, notas TEXT,
 PRIMARY KEY (num_socio), UNIQUE (dni));
CREATE TABLE cuotas (id_cuota VARCHAR NOT NULL, num_socio INTEGER NOT NULL, importe FLOAT,
 PRIMARY KEY (id_cuota), FOREIGN KEY(num_socio) REFERENCES socios (num_socio));
CREATE TABLE historial_socios (id INTEGER NOT NULL, num_socio INTEGER NOT NULL, accion VARCHAR NOT NULL,
 PRIMARY KEY (id), FOREIGN KEY(num_socio) REFERENCES socios (num_socio));
INSERT INTO socios (num_socio,nombre,apellidos,dni,estado,notas) VALUES (1,'Ana','Paz','111A','Al día','n1'),(2,'Luis','Rey','222B','Inactivo',NULL);
INSERT INTO cuotas VALUES ('ARM-CUO2026-001',1,10.0);
INSERT INTO historial_socios VALUES (1,1,'Alta');
"""


class QuitarUnicidadDni(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "asociacion.db"
        con = sqlite3.connect(self.db)
        con.executescript(ESQUEMA_ANTIGUO)
        con.commit()
        con.close()

    def test_migra_conserva_datos_y_permite_dni_repetido(self):
        self.assertTrue(migraciones.quitar_unicidad_dni(self.db))
        con = sqlite3.connect(self.db)
        self.assertEqual(
            con.execute("SELECT num_socio, nombre, dni, estado, notas FROM socios ORDER BY 1").fetchall(),
            [(1, "Ana", "111A", "Al día", "n1"), (2, "Luis", "222B", "Inactivo", None)],
        )
        self.assertEqual(con.execute("SELECT COUNT(*) FROM cuotas").fetchone()[0], 1)
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        for n in (3, 4):   # dos socios con el DNI provisional
            con.execute("INSERT INTO socios (num_socio,nombre,apellidos,dni) VALUES (?,?,?,?)", (n, "X", "Y", "12345678Z"))
        con.commit()
        con.close()

    def test_hace_copia_previa_y_no_repite(self):
        migraciones.quitar_unicidad_dni(self.db)
        self.assertEqual(len(list(self.dir.glob("asociacion_antes_de_migrar_*.db"))), 1)
        self.assertFalse(migraciones.quitar_unicidad_dni(self.db))      # ya migrada
        self.assertEqual(len(list(self.dir.glob("asociacion_antes_de_migrar_*.db"))), 1)

    def test_base_inexistente_o_sin_tabla(self):
        self.assertFalse(migraciones.quitar_unicidad_dni(self.dir / "nada.db"))
        vacia = self.dir / "vacia.db"
        sqlite3.connect(vacia).close()
        self.assertFalse(migraciones.quitar_unicidad_dni(vacia))


if __name__ == "__main__":
    unittest.main()

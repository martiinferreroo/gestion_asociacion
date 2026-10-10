import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tests import helpers  # noqa: F401
import copias
from copias import Programa


def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


class Programacion(unittest.TestCase):
    def test_desactivada_nunca_toca(self):
        p = Programa(activo=False, desde=dt("2026-01-01 00:00"))
        self.assertIsNone(copias.proxima(p, dt("2026-06-01 12:00")))
        self.assertFalse(copias.toca(p, dt("2026-06-01 12:00")))

    def test_diaria_primera_copia_a_la_madrugada_siguiente(self):
        p = Programa(activo=True, hora="03:00", desde=dt("2026-09-29 10:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-29 10:05")), dt("2026-09-30 03:00"))
        self.assertFalse(copias.toca(p, dt("2026-09-30 02:59")))
        self.assertTrue(copias.toca(p, dt("2026-09-30 03:00")))

    def test_diaria_tras_una_copia_toca_al_dia_siguiente(self):
        p = Programa(activo=True, hora="03:00", desde=dt("2026-09-01 10:00"), ultimo=dt("2026-09-30 03:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-30 12:00")), dt("2026-10-01 03:00"))

    def test_servidor_apagado_hace_una_sola_copia_al_arrancar(self):
        p = Programa(activo=True, hora="03:00", ultimo=dt("2026-09-25 03:00"))
        self.assertTrue(copias.toca(p, dt("2026-09-30 18:00")))        # se perdió 5 días
        p.ultimo = dt("2026-09-30 18:00")                                # tras la copia de recuperación
        self.assertFalse(copias.toca(p, dt("2026-09-30 18:01")))
        self.assertEqual(copias.proxima(p, dt("2026-09-30 18:01")), dt("2026-10-01 03:00"))

    def test_cada_n_dias(self):
        p = Programa(activo=True, frecuencia="cada_n_dias", cada_dias=3, hora="23:30", ultimo=dt("2026-09-28 23:30"))
        self.assertEqual(copias.proxima(p, dt("2026-09-29 00:00")), dt("2026-10-01 23:30"))
        p.cada_dias = 0     # valor absurdo: se trata como 1
        self.assertEqual(copias.proxima(p, dt("2026-09-29 00:00")), dt("2026-09-29 23:30"))

    def test_semanal(self):
        # 30/09/2026 es miércoles
        p = Programa(activo=True, frecuencia="semanal", dia_semana=0, hora="04:00", desde=dt("2026-09-30 10:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-30 10:00")), dt("2026-10-05 04:00"))   # lunes
        p.dia_semana = 2    # miércoles, pero la hora de hoy ya pasó
        self.assertEqual(copias.proxima(p, dt("2026-09-30 10:00")), dt("2026-10-07 04:00"))
        p = Programa(activo=True, frecuencia="semanal", dia_semana=2, hora="23:00", desde=dt("2026-09-30 10:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-30 10:00")), dt("2026-09-30 23:00"))   # hoy mismo

    def test_mensual_y_meses_cortos(self):
        p = Programa(activo=True, frecuencia="mensual", dia_mes=15, hora="02:00", desde=dt("2026-09-30 10:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-30 10:00")), dt("2026-10-15 02:00"))
        p = Programa(activo=True, frecuencia="mensual", dia_mes=31, hora="02:00", ultimo=dt("2026-01-31 02:00"))
        self.assertEqual(copias.proxima(p, dt("2026-02-01 00:00")), dt("2026-02-28 02:00"))   # febrero
        p = Programa(activo=True, frecuencia="mensual", dia_mes=5, hora="02:00", ultimo=dt("2026-12-20 02:00"))
        self.assertEqual(copias.proxima(p, dt("2026-12-21 00:00")), dt("2027-01-05 02:00"))   # cambio de año

    def test_hora_invalida_usa_las_3(self):
        p = Programa(activo=True, hora="99:99", desde=dt("2026-09-29 10:00"))
        self.assertEqual(copias.proxima(p, dt("2026-09-29 10:00")).hour, 3)

    def test_parsear_hora(self):
        for texto, esperado in {"03:00": (3, 0), "3:05": (3, 5), "23:59": (23, 59)}.items():
            t = copias.parsear_hora(texto)
            self.assertEqual((t.hour, t.minute), esperado)
        for malo in ["24:00", "12:60", "", None, "abc"]:
            self.assertIsNone(copias.parsear_hora(malo))

    def test_describir(self):
        self.assertEqual(copias.describir(Programa(hora="03:00")), "todos los días a las 03:00")
        self.assertEqual(copias.describir(Programa(frecuencia="cada_n_dias", cada_dias=3, hora="01:30")), "cada 3 días a las 01:30")
        self.assertEqual(copias.describir(Programa(frecuencia="semanal", dia_semana=6)), "los domingo a las 03:00")
        self.assertEqual(copias.describir(Programa(frecuencia="mensual", dia_mes=1)), "el día 1 de cada mes a las 03:00")


class Archivos(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "asociacion.db"
        con = sqlite3.connect(self.db)
        con.executescript("CREATE TABLE socios (n INTEGER); INSERT INTO socios VALUES (1),(2),(3);")
        con.commit()
        con.close()
        self.carpeta = self.dir / "backups"

    def test_crear_copia_es_una_base_de_datos_valida(self):
        destino = copias.crear_copia(self.db, self.carpeta, dt("2026-09-30 03:00"))
        self.assertEqual(destino.name, "asociacion_2026-09-30_030000.db")
        con = sqlite3.connect(destino)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM socios").fetchone()[0], 3)
        con.close()
        self.assertEqual([f.name for f in self.carpeta.iterdir()], [destino.name])   # sin .tmp

    def test_crear_copia_en_caliente_con_la_base_en_uso(self):
        abierta = sqlite3.connect(self.db)
        abierta.execute("INSERT INTO socios VALUES (4)")     # transacción sin confirmar
        destino = copias.crear_copia(self.db, self.carpeta)
        con = sqlite3.connect(destino)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM socios").fetchone()[0], 3)
        con.close()
        abierta.close()

    def test_listar_y_podar_solo_tocan_las_copias_propias(self):
        for i in range(5):
            copias.crear_copia(self.db, self.carpeta, dt("2026-09-25 03:00") + timedelta(days=i))
        (self.carpeta / "notas.txt").write_text("no tocar")
        (self.carpeta / "asociacion_manual.db").write_text("no tocar")
        nombres = [c["nombre"] for c in copias.listar(self.carpeta)]
        self.assertEqual(nombres[0], "asociacion_2026-09-29_030000.db")      # la más reciente primero
        self.assertEqual(len(nombres), 5)
        self.assertEqual(copias.podar(self.carpeta, 2), 3)
        self.assertEqual([c["nombre"] for c in copias.listar(self.carpeta)],
                         ["asociacion_2026-09-29_030000.db", "asociacion_2026-09-28_030000.db"])
        self.assertTrue((self.carpeta / "notas.txt").exists())
        self.assertTrue((self.carpeta / "asociacion_manual.db").exists())

    def test_podar_siempre_deja_al_menos_una(self):
        copias.crear_copia(self.db, self.carpeta, dt("2026-09-25 03:00"))
        copias.crear_copia(self.db, self.carpeta, dt("2026-09-26 03:00"))
        copias.podar(self.carpeta, 0)
        self.assertEqual(len(copias.listar(self.carpeta)), 1)

    def test_listar_carpeta_inexistente(self):
        self.assertEqual(copias.listar(self.dir / "nada"), [])


if __name__ == "__main__":
    unittest.main()

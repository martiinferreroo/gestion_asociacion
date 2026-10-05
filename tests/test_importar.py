import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from tests import helpers  # noqa: F401  (añade src/ al path)
import importar as I

HOY = date(2026, 9, 30)
EXISTENTE = dict(
    nombre="Ana", apellidos="Pérez", dni="99999999R", fecha_nacimiento=None,
    telefono=None, email="vieja@x.es", direccion=None,
    fecha_alta=date(2020, 1, 1), notas="Nota vieja",
)


def plan(filas, mapeo, sobrescribir=False, existentes=None, cabecera=False):
    return I.planificar(filas, mapeo, cabecera, sobrescribir, existentes or {}, HOY)


class Fechas(unittest.TestCase):
    def test_formatos_de_texto(self):
        casos = {
            "5/3/85": date(1985, 3, 5),
            "03/05/1980": date(1980, 5, 3),
            "1980-05-02": date(1980, 5, 2),
            "2 de mayo de 1980": date(1980, 5, 2),
            "7-may-1990": date(1990, 5, 7),
            "02-05-80": date(1980, 5, 2),
            "5051980": date(1980, 5, 5),
            "19800505": date(1980, 5, 5),
            "12/31/1980": date(1980, 12, 31),          # formato americano
            "05/05/1980 00:00:00": date(1980, 5, 5),
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada):
                self.assertEqual(I.parsear_fecha(entrada, True, HOY), esperado)

    def test_valores_de_excel(self):
        self.assertEqual(I.parsear_fecha(datetime(1990, 1, 1, 10, 30), True, HOY), date(1990, 1, 1))
        self.assertEqual(I.parsear_fecha(29000, True, HOY), date(1979, 5, 25))   # nº de serie

    def test_fechas_imposibles(self):
        for v in ["13/25/1980", "31/02/1980", "mañana", "05/05/2030", 1985, None, True]:
            with self.subTest(v):
                self.assertIsNone(I.parsear_fecha(v, True, HOY))

    def test_anio_de_dos_cifras(self):
        self.assertEqual(I.parsear_fecha("5/3/05", True, HOY), date(2005, 3, 5))
        self.assertEqual(I.parsear_fecha("5/3/45", True, HOY), date(1945, 3, 5))


class Dni(unittest.TestCase):
    def test_calcula_la_letra_que_falta(self):
        self.assertEqual(I.limpiar_dni("00000000")[0], "00000000T")
        self.assertEqual(I.limpiar_dni("X0000000")[0], "X0000000T")
        self.assertEqual(I.limpiar_dni("Y-0000000")[0], "Y0000000Z")

    def test_limpia_separadores_y_mayusculas(self):
        self.assertEqual(I.limpiar_dni("99.999.999-r"), ("99999999R", None))

    def test_recupera_el_cero_inicial(self):
        self.assertEqual(I.limpiar_dni("1234567L")[0], "01234567L")

    def test_vacios_y_provisional(self):
        for v in [None, "", "no tiene", "-", "12345678Z", "12345678z"]:
            with self.subTest(v):
                self.assertEqual(I.limpiar_dni(v), (None, None))

    def test_no_valido(self):
        dni, aviso = I.limpiar_dni("ABC")
        self.assertIsNone(dni)
        self.assertIn("no válido", aviso)


class Telefonos(unittest.TestCase):
    def test_numero_de_excel(self):
        self.assertEqual(I.separar_telefonos(600123456.0), (["600 123 456"], []))

    def test_varios_en_una_celda(self):
        v, _ = I.separar_telefonos("981 12 34 56 / 600 111 222")
        self.assertEqual(v, ["981 123 456", "600 111 222"])

    def test_prefijos(self):
        self.assertEqual(I.separar_telefonos("+34 666 555 444")[0], ["+34 666 555 444"])
        self.assertEqual(I.separar_telefonos("0034600123456")[0], ["+34 600 123 456"])

    def test_invalido(self):
        self.assertEqual(I.separar_telefonos("abc"), ([], ["abc"]))


class Correos(unittest.TestCase):
    def test_minusculas(self):
        self.assertEqual(I.separar_emails("ANA@Correo.ES"), (["ana@correo.es"], []))

    def test_varios(self):
        self.assertEqual(I.separar_emails("a@b.es; c@d.es")[0], ["a@b.es", "c@d.es"])

    def test_invalido(self):
        self.assertEqual(I.separar_emails("sin correo"), ([], ["sin correo"]))


class Nombres(unittest.TestCase):
    def test_capitalizar(self):
        self.assertEqual(I.capitalizar("GARCÍA DE LA FUENTE"), "García de la Fuente")
        self.assertEqual(I.capitalizar("ana maría"), "Ana María")
        self.assertEqual(I.capitalizar("María Pérez"), "María Pérez")   # mixto: no se toca

    def test_dividir_nombre_completo(self):
        casos = {
            "Pérez Ruiz, Ana": ("Ana", "Pérez Ruiz"),
            "Juan Carlos Pérez Ruiz": ("Juan Carlos", "Pérez Ruiz"),
            "María García de la Fuente": ("María", "García de la Fuente"),
            "Ana Pérez": ("Ana", "Pérez"),
            "Ana": ("Ana", ""),
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada):
                self.assertEqual(I.dividir_nombre_completo(entrada), esperado)


class Mapeo(unittest.TestCase):
    def test_por_encabezados(self):
        filas = [
            ["Nº Socio", "Apellidos", "Nombre", "DNI/NIE", "F. Nacimiento", "Móvil", "E-mail", "Domicilio", "Observaciones", "Localidad"],
            [1, "Pérez", "Ana", "12345678Z", "02/05/1980", "600123456", "a@b.es", "Rúa 1", "x", "Sada"],
            [2, "Ruiz", "Luis", "11111111H", "05/03/1975", "600123457", "l@b.es", "Rúa 2", "", "Sada"],
        ]
        self.assertEqual(
            I.sugerir_mapeo(filas, True),
            ["num_socio", "apellidos", "nombre", "dni", "fecha_nacimiento",
             "telefono", "email", "direccion", "notas", ""],
        )

    def test_por_contenido_sin_cabecera(self):
        filas = [
            ["ANA PÉREZ RUIZ", "12345678Z", "600 123 456", "ana@x.es", "02/05/1980"],
            ["Ruiz Gómez, Luis", "", "981123456", "", "1975-03-05"],
        ]
        self.assertEqual(
            I.sugerir_mapeo(filas, False),
            ["nombre_completo", "dni", "telefono", "email", "fecha_nacimiento"],
        )

    def test_columna_socio_con_texto_no_es_numero(self):
        filas = [["Socio", "Teléfono"], ["Ana Pérez Ruiz", "600123456"], ["Luis Gómez Ruiz", "600123457"]]
        self.assertNotEqual(I.sugerir_mapeo(filas, True)[0], "num_socio")


class Lectura(unittest.TestCase):
    def test_excel_con_hojas_y_filas_vacias_al_final(self):
        wb = Workbook()
        wb.active.title = "Socios"
        wb.active.append(["Nombre", "Teléfono"])
        wb.active.append(["Ana", 600123456])
        wb.active.append([None, None])
        wb.create_sheet("Otra").append(["x"])
        ruta = Path(tempfile.mkdtemp()) / "t.xlsx"
        wb.save(ruta)
        hojas, usada, filas, recortado = I.cargar(ruta)
        self.assertEqual((hojas, usada, recortado), (["Socios", "Otra"], "Socios", False))
        self.assertEqual(len(filas), 2)
        self.assertEqual(I.cargar(ruta, "Otra")[2], [["x"]])

    def test_csv_con_punto_y_coma_y_acentos_de_windows(self):
        ruta = Path(tempfile.mkdtemp()) / "t.csv"
        ruta.write_bytes("Nombre;Apellidos;Teléfono\nJosé;Núñez;600000001\n".encode("cp1252"))
        _, _, filas, _ = I.cargar(ruta)
        self.assertEqual(filas[1], ["José", "Núñez", "600000001"])


class PlanDeImportacion(unittest.TestCase):
    MAPEO = ["num_socio", "nombre", "apellidos", "dni", "telefono", "email", "notas"]

    def test_la_primera_fila_se_ignora_si_es_cabecera(self):
        filas = [["Nº", "Nombre", "Apellidos", "DNI", "Tel", "Mail", "Notas"],
                 [5, "Ana", "Paz", "", "", "", ""]]
        inf = plan(filas, self.MAPEO, cabecera=True)
        self.assertEqual([o["num"] for o in inf["operaciones"]], [5])
        inf = plan(filas, self.MAPEO, cabecera=False)
        self.assertEqual(inf["nuevos"], 2)   # sin marcar la cabecera, esa fila también se importaría

    def test_sin_dni_se_usa_el_provisional(self):
        inf = plan([[None, "Marta", "López", None, None, None, None]], self.MAPEO)
        self.assertEqual(inf["operaciones"][0]["datos"]["dni"], I.DNI_GENERICO)
        self.assertTrue(any("provisional" in g for g in inf["globales"]))

    def test_sin_numero_se_asigna_el_siguiente_libre(self):
        existentes = {1: dict(EXISTENTE), 7: dict(EXISTENTE, dni="22222222J")}
        inf = plan([[None, "Marta", "López", None, None, None, None]], self.MAPEO, existentes=existentes)
        self.assertEqual(inf["operaciones"][0]["num"], 8)

    def test_sin_sobrescribir_prevalece_lo_existente_y_se_rellenan_huecos(self):
        fila = [1, "Ana María", "Pérez Ruiz", "11111111H", "600123456", "nueva@x.es", "otra nota"]
        inf = plan([fila], self.MAPEO, False, {1: dict(EXISTENTE)})
        op = inf["operaciones"][0]
        self.assertEqual(op["op"], "actualizar")
        d = op["datos"]
        self.assertEqual((d["nombre"], d["apellidos"]), ("Ana", "Pérez"))
        self.assertEqual(d["email"], "vieja@x.es")
        self.assertEqual(d["notas"], "Nota vieja")
        self.assertEqual(d["dni"], "99999999R")
        self.assertEqual(d["telefono"], "600 123 456")           # hueco rellenado
        self.assertTrue(any("se mantienen" in m["texto"] for m in inf["mensajes"]))

    def test_sin_sobrescribir_el_provisional_se_considera_hueco(self):
        existente = dict(EXISTENTE, dni=I.DNI_GENERICO)
        fila = [1, None, None, "11111111H", None, None, None]
        d = plan([fila], self.MAPEO, False, {1: existente})["operaciones"][0]["datos"]
        self.assertEqual(d["dni"], "11111111H")

    def test_sobrescribir_guarda_lo_anterior_en_observaciones(self):
        fila = [1, "Ana María", "Pérez Ruiz", None, "600123456", None, "Nota nueva"]
        inf = plan([fila], self.MAPEO, True, {1: dict(EXISTENTE)})
        d = inf["operaciones"][0]["datos"]
        self.assertEqual((d["nombre"], d["apellidos"]), ("Ana María", "Pérez Ruiz"))
        self.assertEqual(d["dni"], "99999999R")                  # no había DNI nuevo
        self.assertEqual(d["email"], "vieja@x.es")               # columna sin dato: no se borra
        self.assertTrue(d["notas"].startswith("Nota nueva\n[Datos anteriores a la importación del 30/09/2026]"))
        for esperado in ("Nombre: Ana", "Apellidos: Pérez", "Observaciones: Nota vieja"):
            self.assertIn(esperado, d["notas"])

    def test_sobrescribir_sin_cambios_no_toca_nada(self):
        fila = [1, "Ana", "Pérez", None, None, None, None]
        inf = plan([fila], self.MAPEO, True, {1: dict(EXISTENTE)})
        self.assertEqual((inf["actualizados"], inf["sin_cambios"], inf["operaciones"]), (0, 1, []))

    def test_numero_repetido_en_el_archivo_recibe_otro(self):
        filas = [[3, "Pepe", "Souto", None, None, None, None],
                 [3, "Otro", "Repetido", None, None, None, None]]
        nums = [o["num"] for o in plan(filas, self.MAPEO)["operaciones"]]
        self.assertEqual(nums, [3, 4])

    def test_dni_duplicado_de_otro_socio_se_guarda_como_provisional(self):
        existentes = {7: dict(EXISTENTE, dni="22222222J")}
        op = plan([[9, "Luis", "Rey", "22222222J", None, None, None]], self.MAPEO,
                  existentes=existentes)["operaciones"][0]
        self.assertEqual((op["op"], op["num"]), ("crear", 9))
        self.assertEqual(op["datos"]["dni"], I.DNI_GENERICO)
        self.assertIn("22222222J duplicado con el socio #7", op["datos"]["notas"])

    def test_los_numeros_automaticos_no_pisan_los_del_archivo(self):
        filas = [[None, "Ana", "Paz", None, None, None, None],
                 [1, "Luis", "Rey", None, None, None, None]]
        nums = {o["datos"]["nombre"]: o["num"] for o in plan(filas, self.MAPEO)["operaciones"]}
        self.assertEqual(nums, {"Luis": 1, "Ana": 2})

    def test_sin_numero_se_localiza_al_socio_por_dni(self):
        fila = [None, "Ana", "Pérez", "99999999R", "600123456", None, None]
        op = plan([fila], self.MAPEO, False, {1: dict(EXISTENTE)})["operaciones"][0]
        self.assertEqual((op["op"], op["num"]), ("actualizar", 1))

    def test_fila_sin_nombre_se_omite_y_fila_vacia_se_ignora(self):
        filas = [[None, None, None, None, "600123456", None, None],
                 [None, None, None, None, None, None, None]]
        inf = plan(filas, self.MAPEO)
        self.assertEqual((inf["omitidos"], inf["nuevos"], inf["leidas"]), (1, 0, 1))

    def test_lo_que_no_encaja_queda_en_observaciones(self):
        fila = [None, "Luis", "Rey", None, "abc", "sin correo", None]
        d = plan([fila], self.MAPEO)["operaciones"][0]["datos"]
        self.assertIsNone(d["telefono"])
        self.assertIn("teléfono no válido", d["notas"])
        self.assertIn("correo no válido", d["notas"])

    def test_nombre_completo_y_aviso_global(self):
        inf = plan([["Pérez Ruiz, Ana"]], ["nombre_completo"])
        d = inf["operaciones"][0]["datos"]
        self.assertEqual((d["nombre"], d["apellidos"]), ("Ana", "Pérez Ruiz"))
        self.assertTrue(any("dividieron" in g for g in inf["globales"]))

    def test_varias_columnas_de_direccion_se_unen(self):
        inf = plan([["Ana", "Paz", "Rúa Nova", "3", "2ºB"]],
                   ["nombre", "apellidos", "direccion", "direccion", "direccion"])
        self.assertEqual(inf["operaciones"][0]["datos"]["direccion"], "Rúa Nova, 3, 2ºB")

    def test_segundo_telefono_pasa_a_observaciones(self):
        inf = plan([["Ana", "Paz", "600111222", "600333444"]], ["nombre", "apellidos", "telefono", "telefono"])
        d = inf["operaciones"][0]["datos"]
        self.assertEqual(d["telefono"], "600 111 222")
        self.assertIn("600 333 444", d["notas"])


if __name__ == "__main__":
    unittest.main()

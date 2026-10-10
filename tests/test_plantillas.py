import unittest
from datetime import date, datetime
from types import SimpleNamespace as NS

from jinja2 import Environment, FileSystemLoader

from tests import helpers  # noqa: F401
import formatos
import importar

PLANTILLAS = helpers.SRC / "templates"


def entorno():
    env = Environment(loader=FileSystemLoader(PLANTILLAS), autoescape=True)
    env.filters["fecha"] = formatos.fecha
    env.filters["fechahora"] = formatos.fechahora
    env.filters["eur"] = formatos.euros
    env.globals["asset"] = lambda nombre: f"/static/{nombre}?v=1"
    env.globals["DNI_GENERICO"] = importar.DNI_GENERICO
    return env


def contexto(config=None, cuota=None):
    socio = NS(num_socio=25, nombre="Martín", apellidos="Ferrero Ramos", dni="54941437A",
               direccion="Ronda de Outeiro 178", estado="Al día")
    base = dict(
        id_cuota="ARM-CUO2026-001", socio=socio, num_socio=25,
        fecha_pago=datetime(2026, 9, 29, 13, 4), forma_pago="Efectivo", importe=10.0,
        anulada=0, fecha_anulacion=None, motivo_anulacion=None,
    )
    cfg = dict(
        nombre_asociacion="Asociación de Vecinos de Carnoedo", logo_url="/static/uploads/logo_1.png",
        cif="G12345678", direccion="Carnoedo, Sada", telefono="600 111 222", email="a@b.es",
    )
    return dict(
        request=NS(url=NS(path="/cuotas/ARM-CUO2026-001"), query_params={}),
        user=NS(id=1, nombre="Ana", rol="admin"),
        tema=dict(primario="#0f766e", primario_texto="#fff", cabecera="#17343f", cabecera_texto="#fff"),
        config=NS(**{**cfg, **(config or {})}),
        cuota=NS(**{**base, **(cuota or {})}),
        imprimir=True,
    )


class Formatos(unittest.TestCase):
    def test_euros(self):
        self.assertEqual(formatos.euros(10), "10,00 €")
        self.assertEqual(formatos.euros(1234.5), "1.234,50 €")
        self.assertEqual(formatos.euros(None), "0,00 €")

    def test_fechas(self):
        self.assertEqual(formatos.fecha(date(2026, 9, 29)), "29/09/2026")
        self.assertEqual(formatos.fechahora(datetime(2026, 9, 29, 13, 4)), "29/09/2026 13:04")
        self.assertEqual(formatos.fecha(None), "")


class Ticket(unittest.TestCase):
    def render(self, **kw):
        return entorno().get_template("cuotas/ticket.html").render(**contexto(**kw))

    def test_incluye_logo_y_datos_de_la_asociacion(self):
        html = self.render()
        for esperado in ("Asociación de Vecinos de Carnoedo", "CIF G12345678", "Carnoedo, Sada",
                         "Tel. 600 111 222", "a@b.es", 'src="/static/uploads/logo_1.png"'):
            self.assertIn(esperado, html)

    def test_incluye_los_datos_del_recibo(self):
        html = self.render()
        for esperado in ("ARM-CUO2026-001", "29/09/2026 13:04", "Martín Ferrero Ramos",
                         "DNI/NIE 54941437A", "CUOTA ANUAL 2026", "Efectivo", "10,00 €"):
            self.assertIn(esperado, html)
        self.assertNotIn("ANULADO", html)

    def test_sin_logo_ni_datos_opcionales(self):
        html = self.render(config=dict(logo_url=None, cif=None, direccion=None, telefono=None, email=None))
        self.assertNotIn('class="logo"', html)
        self.assertNotIn("CIF", html)
        self.assertNotIn("Tel.", html)

    def test_recibo_anulado(self):
        html = self.render(cuota=dict(anulada=1, fecha_anulacion=datetime(2026, 9, 30, 9, 0), motivo_anulacion="Importe erróneo"))
        self.assertIn("*** ANULADO ***", html)
        self.assertIn("Importe erróneo", html)

    def test_impresion_automatica_solo_si_se_pide(self):
        self.assertIn("data-autoprint", self.render())
        ctx = contexto()
        ctx["imprimir"] = False
        self.assertNotIn("data-autoprint", entorno().get_template("cuotas/ticket.html").render(**ctx))

    def test_se_escapa_el_contenido(self):
        html = self.render(config=dict(nombre_asociacion="<script>alert(1)</script>"))
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_usa_la_hoja_de_estilos_del_ticket(self):
        self.assertIn("/static/ticket.css?v=1", self.render())


class Recibo(unittest.TestCase):
    def test_tiene_botones_de_recibo_y_de_ticket(self):
        html = entorno().get_template("cuotas/detalle.html").render(**contexto())
        self.assertIn("Imprimir recibo", html)
        self.assertIn('href="/cuotas/ARM-CUO2026-001/ticket?imprimir=1"', html)
        self.assertIn("Imprimir ticket", html)
        self.assertIn('target="_blank"', html)

    def test_el_recibo_usa_los_datos_de_ajustes(self):
        html = entorno().get_template("cuotas/detalle.html").render(**contexto())
        for esperado in ("Asociación de Vecinos de Carnoedo", "CIF G12345678", "/static/uploads/logo_1.png"):
            self.assertIn(esperado, html)


if __name__ == "__main__":
    unittest.main()

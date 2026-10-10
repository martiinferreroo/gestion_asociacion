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
    env.filters["fecha_larga"] = formatos.fecha_larga
    env.filters["tamano"] = formatos.tamano
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


class FormatosNuevos(unittest.TestCase):
    def test_fecha_larga_en_espanol(self):
        self.assertEqual(formatos.fecha_larga(date(2026, 9, 29)), "Martes, 29 de septiembre de 2026")
        self.assertEqual(formatos.fecha_larga(datetime(2026, 1, 1, 10, 0)), "Jueves, 1 de enero de 2026")
        self.assertEqual(formatos.fecha_larga(None), "")

    def test_tamano(self):
        self.assertEqual(formatos.tamano(845), "845 B")
        self.assertEqual(formatos.tamano(12595), "12,3 KB")
        self.assertEqual(formatos.tamano(5 * 1024 * 1024), "5,0 MB")
        self.assertEqual(formatos.tamano(None), "0 B")


def nota(id_, texto, hora, usuario_id=1, nombre="Ana", dia=date(2026, 9, 29)):
    return NS(id=id_, texto=texto, creada=datetime(2026, 9, 29, *hora), usuario_id=usuario_id,
              usuario=NS(nombre=nombre) if nombre else None, fecha=dia)


def contexto_agenda(user_id=1, rol="admin", notas=None, dia=date(2026, 9, 29)):
    ctx = contexto()
    ctx["user"] = NS(id=user_id, nombre="Ana", rol=rol)
    ctx["request"] = NS(url=NS(path="/agenda"), query_params={})
    ctx.update(
        dia=dia, notas=notas if notas is not None else [], es_hoy=False,
        anterior=date(2026, 9, 28), siguiente=date(2026, 9, 30), hoy=date(2026, 9, 30),
        recientes=[(date(2026, 9, 29), 2), (date(2026, 9, 25), 1)], max_nota=2000,
    )
    return ctx


class Agenda(unittest.TestCase):
    def render(self, **kw):
        return entorno().get_template("agenda.html").render(**contexto_agenda(**kw))

    def test_muestra_fecha_notas_autor_y_hora(self):
        html = self.render(notas=[nota(1, "Llamar al fontanero", (9, 30), nombre="Luis", usuario_id=2)])
        for esperado in ("Martes, 29 de septiembre de 2026", "Llamar al fontanero", "Luis", "09:30"):
            self.assertIn(esperado, html)

    def test_dia_sin_notas_y_lista_de_dias(self):
        html = self.render()
        self.assertIn("Nada anotado este día.", html)
        self.assertIn("29/09/2026", html)
        self.assertIn("2 notas", html)
        self.assertIn("1 nota</span>", html)

    def test_enlaces_de_navegacion_y_formulario(self):
        html = self.render()
        self.assertIn('href="/agenda?fecha=2026-09-28"', html)
        self.assertIn('href="/agenda?fecha=2026-09-30"', html)
        self.assertIn('name="fecha" value="2026-09-29"', html)
        self.assertIn('action="/agenda"', html)

    def test_solo_el_autor_o_un_admin_ven_el_boton_de_eliminar(self):
        n = [nota(7, "x", (9, 0), usuario_id=2)]
        self.assertIn("/agenda/7/eliminar", self.render(notas=n, user_id=1, rol="admin"))
        self.assertIn("/agenda/7/eliminar", self.render(notas=n, user_id=2, rol="gestor"))
        self.assertNotIn("/agenda/7/eliminar", self.render(notas=n, user_id=3, rol="gestor"))

    def test_nota_escrita_otro_dia_muestra_la_fecha_completa(self):
        n = [nota(1, "x", (9, 0), dia=date(2026, 9, 20))]
        self.assertIn("29/09/2026 09:00", self.render(notas=n, dia=date(2026, 9, 20)))

    def test_el_texto_se_escapa_y_se_conservan_saltos(self):
        html = self.render(notas=[nota(1, "<script>alert(1)</script>", (9, 0))])
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_menu_tiene_enlace_a_la_agenda(self):
        self.assertIn('href="/agenda"', self.render())


def contexto_ajustes(**cfg):
    ctx = contexto(config=dict(
        importe_cuota_defecto=10.0, color_primario=None, color_cabecera=None,
        backup_activo=1, backup_frecuencia="semanal", backup_cada_dias=3, backup_dia_semana=2,
        backup_dia_mes=15, backup_hora="03:30", backup_conservar=10,
        backup_ultimo=datetime(2026, 9, 29, 3, 30), backup_ultimo_estado="Correcta: asociacion_2026-09-29_033000.db",
        **cfg,
    ))
    ctx["request"] = NS(url=NS(path="/ajustes"), query_params={})
    ctx.update(
        usuarios=[NS(id=1, nombre="Ana", username="ana", rol="admin", activo=1)],
        def_primario="#0f766e", def_cabecera="#17343f",
        frecuencias=[("diaria", "Todos los días"), ("cada_n_dias", "Cada varios días"),
                     ("semanal", "Una vez a la semana"), ("mensual", "Una vez al mes")],
        dias_semana=["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
        proxima_copia=datetime(2026, 10, 7, 3, 30), descripcion_copia="los miércoles a las 03:30",
        lista_copias=[{"nombre": "asociacion_2026-09-29_033000.db", "bytes": 20480, "fecha": datetime(2026, 9, 29, 3, 30)}],
        carpeta_copias="/backups",
    )
    return ctx


class AjustesCopias(unittest.TestCase):
    def render(self, **cfg):
        return entorno().get_template("ajustes.html").render(**contexto_ajustes(**cfg))

    def test_muestra_la_configuracion_guardada(self):
        html = self.render()
        self.assertIn('name="backup_activo" value="1" checked', html)
        self.assertIn('<option value="semanal" selected>', html)
        self.assertIn('<option value="2" selected>Miércoles</option>', html)
        self.assertIn('name="backup_hora" value="03:30"', html)
        self.assertIn('name="backup_conservar" min="1" max="365" value="10"', html)

    def test_muestra_proxima_y_ultima_copia(self):
        html = self.render()
        self.assertIn("los miércoles a las 03:30", html)
        self.assertIn("07/10/2026 03:30", html)
        self.assertIn("Correcta: asociacion_2026-09-29_033000.db", html)

    def test_lista_de_copias_con_descarga_y_boton_de_copia_ahora(self):
        html = self.render()
        self.assertIn('href="/ajustes/backups/asociacion_2026-09-29_033000.db"', html)
        self.assertIn("20,0 KB", html)
        self.assertIn('action="/ajustes/backups/ahora"', html)
        self.assertIn("/backups", html)

    def test_desactivadas(self):
        ctx = contexto_ajustes()
        ctx["config"].backup_activo = 0
        ctx["proxima_copia"] = None
        html = entorno().get_template("ajustes.html").render(**ctx)
        self.assertIn("desactivadas", html)
        self.assertNotIn('name="backup_activo" value="1" checked', html)

    def test_error_de_la_ultima_copia_se_destaca(self):
        ctx = contexto_ajustes()
        ctx["config"].backup_ultimo_estado = "Error: disco lleno"
        html = entorno().get_template("ajustes.html").render(**ctx)
        self.assertIn("Error: disco lleno", html)
        self.assertIn("color:var(--danger)", html)

    def test_sin_copias_guardadas(self):
        ctx = contexto_ajustes()
        ctx["lista_copias"] = []
        self.assertIn("Todavía no hay copias guardadas.", entorno().get_template("ajustes.html").render(**ctx))


if __name__ == "__main__":
    unittest.main()

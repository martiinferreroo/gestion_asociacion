import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

import auth
import copias
import exportar
import formatos
import importar
import migraciones
import models
from database import BACKUPS_DIR, BASE_DIR, DATA_DIR, DB_PATH, SessionLocal, engine, get_db

STATIC_DIR = BASE_DIR / "static"
# Con ASOCIACION_DATA (Docker) el logo se guarda en la carpeta de datos; sin
# ella se mantiene la ubicación de siempre.
UPLOAD_DIR = (
    DATA_DIR / "uploads" if "ASOCIACION_DATA" in os.environ else STATIC_DIR / "uploads"
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

COOKIE = "sesion"
PREFIJO_RECIBO = "ARM-CUO"
FORMAS_PAGO = ["Efectivo", "Tarjeta", "Transferencia"]
CLAVE_INICIAL = "admin123"

COLOR_PRIMARIO = "#0f766e"
COLOR_CABECERA = "#17343f"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ESTADOS = [
    ("Al día", "#16a34a"),
    ("Pendiente", "#eab308"),
    ("Inactivo", "#3b82f6"),
    ("Baja (automática)", "#94a3b8"),
    ("Baja (manual)", "#475569"),
]

NO_ANULADA = func.coalesce(models.Cuota.anulada, 0) == 0


# --------------------------------------------------------------------------
# Arranque y migración
# --------------------------------------------------------------------------

def migrar_esquema():
    """Añade a una base de datos existente las columnas nuevas."""
    nuevas = {
        "configuracion": {
            "color_primario": "VARCHAR",
            "color_cabecera": "VARCHAR",
            "backup_activo": "INTEGER DEFAULT 0",
            "backup_frecuencia": "VARCHAR DEFAULT 'diaria'",
            "backup_cada_dias": "INTEGER DEFAULT 1",
            "backup_dia_semana": "INTEGER DEFAULT 0",
            "backup_dia_mes": "INTEGER DEFAULT 1",
            "backup_hora": "VARCHAR DEFAULT '03:00'",
            "backup_conservar": "INTEGER DEFAULT 14",
            "backup_desde": "DATETIME",
            "backup_ultimo": "DATETIME",
            "backup_ultimo_estado": "VARCHAR",
        },
        "cuotas": {
            "anulada": "INTEGER DEFAULT 0",
            "fecha_anulacion": "DATETIME",
            "motivo_anulacion": "VARCHAR",
        },
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for tabla, columnas in nuevas.items():
            existentes = {c["name"] for c in insp.get_columns(tabla)}
            for nombre, tipo in columnas.items():
                if nombre not in existentes:
                    conn.execute(
                        text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
                    )


def get_or_create_config(db: Session):
    config = db.get(models.Configuracion, 1)
    if not config:
        config = models.Configuracion(
            id=1,
            nombre_asociacion="Asociación de Vecinos de Carnoedo ARMENTAL",
            importe_cuota_defecto=10.0,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def crear_admin_inicial(db: Session):
    hay_admin = (
        db.query(models.Usuario).filter(models.Usuario.rol == "admin").first()
    )
    if not hay_admin:
        db.add(
            models.Usuario(
                username="admin",
                password_hash=auth.hash_password(CLAVE_INICIAL),
                nombre="Administrador",
                rol="admin",
                activo=1,
            )
        )
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migraciones.quitar_unicidad_dni(DB_PATH)
    models.Base.metadata.create_all(bind=engine)
    migrar_esquema()
    with SessionLocal() as db:
        get_or_create_config(db)
        crear_admin_inicial(db)
        comprobar_estados_socios(db)
    parar = threading.Event()
    hilo = threading.Thread(target=bucle_copias, args=(parar,), daemon=True, name="copias")
    hilo.start()
    yield
    parar.set()


app = FastAPI(
    title="Gestión de Asociación",
    lifespan=lifespan,
    docs_url=None,       # /docs, /redoc y /openapi.json mostrarían todas las
    redoc_url=None,      # rutas de la aplicación sin necesidad de iniciar sesión
    openapi_url=None,
)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "same-origin")
    if "text/html" in respuesta.headers.get("content-type", ""):
        # Que el navegador no guarde páginas con datos personales
        respuesta.headers.setdefault("Cache-Control", "no-store")
    return respuesta
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def asset(nombre: str) -> str:
    """URL de un estático con su fecha de modificación, para que el navegador
    nunca use una versión antigua guardada en caché."""
    ruta = STATIC_DIR / nombre
    version = int(ruta.stat().st_mtime) if ruta.exists() else 0
    return f"/static/{nombre}?v={version}"


templates.env.globals["asset"] = asset
templates.env.globals["DNI_GENERICO"] = importar.DNI_GENERICO


# --------------------------------------------------------------------------
# Filtros y tema
# --------------------------------------------------------------------------

templates.env.filters["fecha"] = formatos.fecha
templates.env.filters["fechahora"] = formatos.fechahora
templates.env.filters["eur"] = formatos.euros
templates.env.filters["fecha_larga"] = formatos.fecha_larga
templates.env.filters["tamano"] = formatos.tamano


def color_valido(valor, defecto):
    return valor if valor and HEX.match(valor) else defecto


def color_texto(hex_color):
    """Blanco u oscuro, según cuál se lea mejor sobre el color dado."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    luminosidad = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#0f172a" if luminosidad > 0.6 else "#ffffff"


def calcular_tema(config):
    primario = color_valido(config.color_primario, COLOR_PRIMARIO)
    cabecera = color_valido(config.color_cabecera, COLOR_CABECERA)
    return {
        "primario": primario,
        "primario_texto": color_texto(primario),
        "cabecera": cabecera,
        "cabecera_texto": color_texto(cabecera),
    }


def render(request, db, user, name, status_code=200, **ctx):
    config = get_or_create_config(db)
    ctx.update(user=user, config=config, tema=calcular_tema(config))
    return templates.TemplateResponse(
        request=request, name=name, context=ctx, status_code=status_code
    )


def volver(url, ok=None, error=None):
    params = []
    if ok:
        params.append("ok=" + quote(ok))
    if error:
        params.append("error=" + quote(error))
    if params:
        url += ("&" if "?" in url else "?") + "&".join(params)
    return RedirectResponse(url, status_code=303)


# --------------------------------------------------------------------------
# Autenticación y permisos
# --------------------------------------------------------------------------

class NoAutenticado(Exception):
    pass


class SinPermiso(Exception):
    pass


def usuario_actual(request: Request, db: Session = Depends(get_db)):
    user_id = auth.leer_token(request.cookies.get(COOKIE, ""))
    user = db.get(models.Usuario, user_id) if user_id else None
    if not user or not user.activo:
        raise NoAutenticado()
    return user


def solo_admin(user=Depends(usuario_actual)):
    if user.rol != "admin":
        raise SinPermiso(user)
    return user


@app.exception_handler(NoAutenticado)
async def _no_autenticado(request: Request, exc: NoAutenticado):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(SinPermiso)
async def _sin_permiso(request: Request, exc: SinPermiso):
    with SessionLocal() as db:
        return render(
            request,
            db,
            exc.args[0] if exc.args else None,
            "error.html",
            status_code=403,
            titulo="Sin permiso",
            mensaje="Esta sección solo está disponible para administradores.",
        )


@app.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, None, "login.html", error=None)


# Límite de intentos fallidos (en memoria; la aplicación corre en un solo proceso)
INTENTOS_FALLIDOS = {}
VENTANA_BLOQUEO = 300  # segundos
MAX_POR_USUARIO = 5
MAX_POR_IP = 20


def _bloqueado(clave: str, maximo: int) -> bool:
    dato = INTENTOS_FALLIDOS.get(clave)
    if not dato:
        return False
    fallos, desde = dato
    if time.time() - desde > VENTANA_BLOQUEO:
        INTENTOS_FALLIDOS.pop(clave, None)
        return False
    return fallos >= maximo


def _registrar_fallo(clave: str):
    ahora = time.time()
    if len(INTENTOS_FALLIDOS) > 5000:
        for k, (_, desde) in list(INTENTOS_FALLIDOS.items()):
            if ahora - desde > VENTANA_BLOQUEO:
                INTENTOS_FALLIDOS.pop(k, None)
    fallos, desde = INTENTOS_FALLIDOS.get(clave, (0, ahora))
    if ahora - desde > VENTANA_BLOQUEO:
        fallos, desde = 0, ahora
    INTENTOS_FALLIDOS[clave] = (fallos + 1, desde)


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    clave_usuario = "u:" + username.strip().lower()
    clave_ip = "i:" + (request.client.host if request.client else "?")
    if _bloqueado(clave_usuario, MAX_POR_USUARIO) or _bloqueado(clave_ip, MAX_POR_IP):
        return render(
            request, db, None, "login.html", status_code=429,
            error="Demasiados intentos fallidos. Espera unos minutos.",
        )
    user = (
        db.query(models.Usuario)
        .filter(func.lower(models.Usuario.username) == username.strip().lower())
        .first()
    )
    if (
        not user
        or not auth.verify_password(password, user.password_hash)
    ):
        _registrar_fallo(clave_usuario)
        _registrar_fallo(clave_ip)
        return render(
            request, db, None, "login.html", status_code=401,
            error="Usuario o contraseña incorrectos.",
        )
    INTENTOS_FALLIDOS.pop(clave_usuario, None)
    if not user.activo:
        return render(
            request, db, None, "login.html", status_code=403,
            error="Este usuario está desactivado.",
        )

    if password == CLAVE_INICIAL:
        respuesta = volver(
            f"/usuarios/{user.id}/password",
            error="Estás usando la contraseña inicial. Cámbiala antes de continuar.",
        )
    else:
        respuesta = RedirectResponse("/", status_code=303)
    # Cookie solo por HTTPS cuando la petición llega cifrada (o si se fuerza
    # con ASOCIACION_COOKIE_SECURE=1, útil tras un proxy inverso).
    segura = (
        request.url.scheme == "https"
        or os.environ.get("ASOCIACION_COOKIE_SECURE") == "1"
    )
    respuesta.set_cookie(
        COOKIE,
        auth.crear_token(user.id),
        httponly=True,
        secure=segura,
        samesite="lax",
        max_age=auth.SESSION_SECONDS,
    )
    return respuesta


@app.post("/logout")
def logout():
    respuesta = RedirectResponse("/login", status_code=303)
    respuesta.delete_cookie(COOKIE)
    return respuesta


# --------------------------------------------------------------------------
# Lógica de negocio
# --------------------------------------------------------------------------

def comprobar_estados_socios(db: Session):
    ultimas = dict(
        db.query(models.Cuota.num_socio, func.max(models.Cuota.fecha_pago))
        .filter(NO_ANULADA)
        .group_by(models.Cuota.num_socio)
        .all()
    )
    hoy = date.today()
    hay_cambios = False

    for socio in db.query(models.Socio).all():
        if socio.estado == "Baja (manual)":
            continue
        ultima = ultimas.get(socio.num_socio)
        if ultima is None:
            nuevo = "Inactivo"
        else:
            if isinstance(ultima, str):
                ultima = datetime.fromisoformat(ultima)
            dias = (hoy - ultima.date()).days
            if dias < 365:
                nuevo = "Al día"
            elif dias <= 730:
                nuevo = "Pendiente"
            else:
                nuevo = "Baja (automática)"
        if socio.estado != nuevo:
            socio.estado = nuevo
            hay_cambios = True

    if hay_cambios:
        db.commit()


def generar_id_cuota(db: Session, fecha_pago: datetime) -> str:
    prefijo = f"{PREFIJO_RECIBO}{fecha_pago.year}-"
    ids = (
        db.query(models.Cuota.id_cuota)
        .filter(models.Cuota.id_cuota.like(f"{prefijo}%"))
        .all()
    )
    maximo = 0
    for (id_cuota,) in ids:
        try:
            maximo = max(maximo, int(id_cuota.split("-")[-1]))
        except ValueError:
            pass
    return f"{prefijo}{maximo + 1:03d}"


def anotar(db, num_socio, user, accion, detalles):
    db.add(
        models.HistorialSocio(
            num_socio=num_socio,
            usuario_id=user.id,
            accion=accion,
            detalles=detalles,
        )
    )


def limpio(valor):
    return (valor or "").strip() or None


# --------------------------------------------------------------------------
# Panel principal
# --------------------------------------------------------------------------

@app.get("/")
def home(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    comprobar_estados_socios(db)

    conteo = dict(
        db.query(models.Socio.estado, func.count())
        .group_by(models.Socio.estado)
        .all()
    )
    total = sum(conteo.values())
    estados = [
        {"nombre": n, "color": c, "n": conteo.get(n, 0)} for n, c in ESTADOS
    ]

    partes, acumulado = [], 0
    for e in estados:
        if e["n"]:
            inicio = acumulado / total * 100
            acumulado += e["n"]
            partes.append(f"{e['color']} {inicio:.2f}% {acumulado / total * 100:.2f}%")
    donut = (
        f"conic-gradient({', '.join(partes)})"
        if partes
        else "conic-gradient(#e2e8f0 0 100%)"
    )

    hoy = date.today()
    recaudado = (
        db.query(func.coalesce(func.sum(models.Cuota.importe), 0))
        .filter(NO_ANULADA, models.Cuota.fecha_pago >= datetime(hoy.year, 1, 1))
        .scalar()
    )
    ultimos_pagos = (
        db.query(models.Cuota)
        .order_by(models.Cuota.fecha_pago.desc())
        .limit(5)
        .all()
    )
    cumpleanios = sorted(
        (
            s
            for s in db.query(models.Socio)
            .filter(models.Socio.estado.in_(["Al día", "Pendiente"]))
            .all()
            if s.fecha_nacimiento and s.fecha_nacimiento.month == hoy.month
        ),
        key=lambda s: s.fecha_nacimiento.day,
    )

    return render(
        request, db, user, "dashboard.html",
        total=total, estados=estados, donut=donut, recaudado=recaudado,
        ultimos_pagos=ultimos_pagos, cumpleanios=cumpleanios, anio=hoy.year,
        hoy=hoy,
    )


# --------------------------------------------------------------------------
# Socios
# --------------------------------------------------------------------------

def normalizar_dni(valor):
    return re.sub(r"[\s.-]", "", valor or "").upper()


def validar_socio(db, datos, num_editando=None):
    if not datos["nombre"] or not datos["apellidos"] or not datos["dni"]:
        return "Nombre, apellidos y DNI son obligatorios.", None
    existente = None
    if datos["dni"] != importar.DNI_GENERICO:
        existente = (
            db.query(models.Socio)
            .filter(func.upper(models.Socio.dni) == datos["dni"])
            .first()
        )
    if existente and existente.num_socio != num_editando:
        return (
            f"Ya existe un socio con el DNI {datos['dni']} "
            f"(#{existente.num_socio}).",
            None,
        )
    if num_editando is None:
        if datos["num_socio"] < 1:
            return "El número de socio debe ser mayor que cero.", None
        if db.get(models.Socio, datos["num_socio"]):
            return f"El número de socio #{datos['num_socio']} ya está asignado.", None
    if datos["email"] and not EMAIL.match(datos["email"]):
        return "El correo electrónico no parece válido.", None
    f_nac = None
    if datos["fecha_nacimiento"]:
        try:
            f_nac = date.fromisoformat(datos["fecha_nacimiento"])
        except ValueError:
            return "La fecha de nacimiento no es válida.", None
        if f_nac > date.today():
            return "La fecha de nacimiento no puede ser futura.", None
    return None, f_nac


@app.get("/socios")
def listado_socios(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    comprobar_estados_socios(db)
    socios = db.query(models.Socio).order_by(models.Socio.num_socio).all()
    return render(request, db, user, "socios/listado.html", socios=socios)


# --------------------------------------------------------------------------
# Importación desde Excel / CSV
# --------------------------------------------------------------------------

IMPORT_DIR = Path(tempfile.gettempdir()) / "asociacion_import"
COPIAS_DIR = DATA_DIR / "copias"
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def guardar_temporal(archivo: UploadFile) -> str:
    ext = Path(archivo.filename or "").suffix.lower()
    if ext == ".xls":
        raise ValueError(
            "El formato .xls antiguo no se puede leer. Ábrelo en Excel y "
            "guárdalo como .xlsx."
        )
    if ext not in importar.EXTENSIONES:
        raise ValueError("El archivo debe ser de Excel (.xlsx) o CSV (.csv).")
    datos = archivo.file.read(importar.MAX_BYTES + 1)
    if len(datos) > importar.MAX_BYTES:
        raise ValueError("El archivo pesa más de 5 MB.")
    IMPORT_DIR.mkdir(exist_ok=True)
    ahora = time.time()
    for viejo in IMPORT_DIR.glob("*"):
        if ahora - viejo.stat().st_mtime > 7200:
            viejo.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    (IMPORT_DIR / f"{token}{ext}").write_bytes(datos)
    return token


def ruta_temporal(token: str):
    if not TOKEN_RE.match(token):
        return None
    for ruta in IMPORT_DIR.glob(f"{token}.*"):
        return ruta
    return None


def copia_previa():
    """Copia automática de la base de datos antes de importar."""
    COPIAS_DIR.mkdir(exist_ok=True)
    destino = COPIAS_DIR / f"asociacion_antes_de_importar_{datetime.now():%Y%m%d_%H%M%S}.db"
    origen_con = sqlite3.connect(DB_PATH)
    destino_con = sqlite3.connect(destino)
    with destino_con:
        origen_con.backup(destino_con)
    origen_con.close()
    destino_con.close()
    for viejo in sorted(COPIAS_DIR.glob("asociacion_antes_de_importar_*.db"))[:-10]:
        viejo.unlink(missing_ok=True)
    return destino


def aplicar_plan(db: Session, user, operaciones):
    for op in operaciones:
        if op["op"] == "crear":
            db.add(models.Socio(num_socio=op["num"], estado="Inactivo", **op["datos"]))
            db.flush()
        else:
            socio = db.get(models.Socio, op["num"])
            for campo, valor in op["datos"].items():
                setattr(socio, campo, valor)
        anotar(db, op["num"], user, op["accion"], op["detalle"])


def render_mapa(request, db, user, token, lectura, cabecera, mapeo=None,
                sobrescribir=False, error=None, status_code=200):
    hojas, usada, filas, recortado = lectura
    ncols = len(filas[0])
    if mapeo is None or len(mapeo) != ncols:
        mapeo = importar.sugerir_mapeo(filas, cabecera)
    encabezados = (
        [importar.texto(c) for c in filas[0]] if cabecera else [""] * ncols
    )
    cuerpo = filas[1:] if cabecera else filas
    return render(
        request, db, user, "socios/importar_mapa.html", status_code=status_code,
        token=token, hojas=hojas, hoja=usada, cabecera=cabecera,
        recortado=recortado, ncols=ncols, mapeo=mapeo,
        encabezados=encabezados, total=len(cuerpo),
        vista=[[importar.texto(c) for c in f] for f in cuerpo[:8]],
        letras=[importar.letra(j) for j in range(ncols)],
        opciones=importar.CAMPOS_DESTINO, sobrescribir=sobrescribir,
        error=error, max_filas=importar.MAX_FILAS,
    )


def leer_archivo_importado(ruta, hoja):
    """Devuelve (lectura, mensaje_de_error)."""
    try:
        lectura = importar.cargar(ruta, hoja)
    except Exception:
        return None, "No se pudo leer el archivo. ¿Está dañado o protegido con contraseña?"
    if not lectura[2]:
        return None, "El archivo no contiene datos."
    return lectura, None


@app.get("/socios/importar")
def importar_form(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    return render(request, db, user, "socios/importar.html", error=None)


@app.post("/socios/importar")
def importar_subir(
    request: Request,
    archivo: UploadFile = File(None),
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    if archivo is None or not archivo.filename:
        return render(request, db, user, "socios/importar.html",
                      status_code=400, error="Selecciona un archivo.")
    try:
        token = guardar_temporal(archivo)
    except ValueError as e:
        return render(request, db, user, "socios/importar.html",
                      status_code=400, error=str(e))
    return RedirectResponse(f"/socios/importar/{token}", status_code=303)


@app.get("/socios/importar/{token}")
def importar_mapa(
    token: str,
    request: Request,
    hoja: str = None,
    cabecera: str = None,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    ruta = ruta_temporal(token)
    if not ruta:
        return volver("/socios/importar",
                      error="El archivo ya no está disponible. Súbelo de nuevo.")
    lectura, error = leer_archivo_importado(ruta, hoja)
    if error:
        return volver("/socios/importar", error=error)
    return render_mapa(request, db, user, token, lectura, cabecera != "0")


@app.post("/socios/importar/{token}")
async def importar_procesar(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    ruta = ruta_temporal(token)
    if not ruta:
        return volver("/socios/importar",
                      error="El archivo ya no está disponible. Súbelo de nuevo.")
    form = await request.form()
    cabecera = form.get("cabecera") != "0"
    sobrescribir = form.get("sobrescribir") is not None
    lectura, error = leer_archivo_importado(ruta, form.get("hoja") or None)
    if error:
        return volver("/socios/importar", error=error)
    filas = lectura[2]

    mapeo = []
    for j in range(len(filas[0])):
        destino = form.get(f"col_{j}") or ""
        mapeo.append(destino if destino in importar.CLAVES else "")
    if form.get("accion") == "ajustar":
        return render_mapa(request, db, user, token, lectura, cabecera, mapeo, sobrescribir)
    if not set(mapeo) & {"nombre", "apellidos", "nombre_completo", "num_socio", "dni"}:
        return render_mapa(
            request, db, user, token, lectura, cabecera, mapeo, sobrescribir,
            "Indica qué columna contiene el nombre, el Nº de socio o el DNI.", 400,
        )

    existentes = {
        s.num_socio: {c: getattr(s, c) for c in importar.CAMPOS_DATOS}
        for s in db.query(models.Socio).all()
    }
    informe = importar.planificar(filas, mapeo, cabecera, sobrescribir, existentes)
    if lectura[3]:
        informe["globales"].insert(
            0, f"El archivo tiene más de {importar.MAX_FILAS} filas: solo se han leído las primeras."
        )

    guardado = False
    if form.get("accion") == "importar":
        try:
            copia_previa()
            aplicar_plan(db, user, informe["operaciones"])
            db.commit()
        except Exception:
            db.rollback()
            return render_mapa(
                request, db, user, token, lectura, cabecera, mapeo, sobrescribir,
                "La importación ha fallado y no se ha guardado nada. Revisa el archivo.", 500,
            )
        comprobar_estados_socios(db)
        ruta.unlink(missing_ok=True)
        guardado = True

    campos = [(k, v) for k, v in form.multi_items()
              if k != "accion" and isinstance(v, str)]
    return render(
        request, db, user, "socios/importar_resultado.html", informe=informe,
        guardado=guardado, token=token, campos=campos,
        mensajes=informe["mensajes"][:300], sobrescribir=sobrescribir,
    )


@app.get("/socios/exportar")
def exportar_socios(
    db: Session = Depends(get_db),
    user=Depends(solo_admin),  # cámbialo por usuario_actual para abrirlo a los gestores
):
    socios = (
        db.query(models.Socio)
        .order_by(func.lower(models.Socio.apellidos), func.lower(models.Socio.nombre))
        .all()
    )
    tema = calcular_tema(get_or_create_config(db))
    contenido = exportar.construir_excel_socios(
        socios, tema["primario"], tema["primario_texto"]
    )
    nombre = f"socios_{datetime.now():%Y%m%d}.xlsx"
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.get("/socios/nuevo")
def nuevo_socio_form(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    siguiente = (db.query(func.max(models.Socio.num_socio)).scalar() or 0) + 1
    return render(
        request, db, user, "socios/form.html", modo="nuevo",
        datos={"num_socio": siguiente}, error=None,
    )


@app.post("/socios/nuevo")
def guardar_socio(
    request: Request,
    num_socio: int = Form(...),
    nombre: str = Form(""),
    apellidos: str = Form(""),
    dni: str = Form(""),
    fecha_nacimiento: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    direccion: str = Form(""),
    notas: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    datos = {
        "num_socio": num_socio,
        "nombre": nombre.strip(),
        "apellidos": apellidos.strip(),
        "dni": normalizar_dni(dni),
        "fecha_nacimiento": fecha_nacimiento.strip(),
        "telefono": telefono.strip(),
        "email": email.strip(),
        "direccion": direccion.strip(),
        "notas": notas.strip(),
    }
    error, f_nac = validar_socio(db, datos)
    if error:
        return render(
            request, db, user, "socios/form.html", status_code=400,
            modo="nuevo", datos=datos, error=error,
        )

    socio = models.Socio(
        num_socio=num_socio,
        nombre=datos["nombre"],
        apellidos=datos["apellidos"],
        dni=datos["dni"],
        fecha_nacimiento=f_nac,
        telefono=limpio(telefono),
        email=limpio(email),
        direccion=limpio(direccion),
        notas=limpio(notas),
        estado="Inactivo",
    )
    db.add(socio)
    db.flush()
    anotar(db, socio.num_socio, user, "Alta de socio",
           f"Socio registrado con el número #{socio.num_socio}.")
    db.commit()
    return volver(f"/socios/{socio.num_socio}", ok="Socio registrado.")


@app.get("/socios/{num_socio}")
def ficha_socio(
    num_socio: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    socio = db.get(models.Socio, num_socio)
    if not socio:
        return volver("/socios", error="Ese socio no existe.")
    historial = (
        db.query(models.HistorialSocio)
        .filter(models.HistorialSocio.num_socio == num_socio)
        .order_by(models.HistorialSocio.fecha_registro.desc(),
                  models.HistorialSocio.id.desc())
        .all()
    )
    cuotas = (
        db.query(models.Cuota)
        .filter(models.Cuota.num_socio == num_socio)
        .order_by(models.Cuota.fecha_pago.desc())
        .all()
    )
    return render(request, db, user, "socios/ficha.html",
                  socio=socio, historial=historial, cuotas=cuotas)


@app.get("/socios/{num_socio}/editar")
def editar_socio_form(
    num_socio: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    socio = db.get(models.Socio, num_socio)
    if not socio:
        return volver("/socios", error="Ese socio no existe.")
    return render(request, db, user, "socios/form.html", modo="editar",
                  socio=socio, datos=socio, error=None)


@app.post("/socios/{num_socio}/editar")
def editar_socio(
    num_socio: int,
    request: Request,
    nombre: str = Form(""),
    apellidos: str = Form(""),
    dni: str = Form(""),
    fecha_nacimiento: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    direccion: str = Form(""),
    notas: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    socio = db.get(models.Socio, num_socio)
    if not socio:
        return volver("/socios", error="Ese socio no existe.")

    datos = {
        "num_socio": num_socio,
        "nombre": nombre.strip(),
        "apellidos": apellidos.strip(),
        "dni": normalizar_dni(dni),
        "fecha_nacimiento": fecha_nacimiento.strip(),
        "telefono": telefono.strip(),
        "email": email.strip(),
        "direccion": direccion.strip(),
        "notas": notas.strip(),
    }
    error, f_nac = validar_socio(db, datos, num_editando=num_socio)
    if error:
        return render(
            request, db, user, "socios/form.html", status_code=400,
            modo="editar", socio=socio, datos=datos, error=error,
        )

    nuevos = {
        "nombre": datos["nombre"],
        "apellidos": datos["apellidos"],
        "dni": datos["dni"],
        "fecha_nacimiento": f_nac,
        "telefono": limpio(telefono),
        "email": limpio(email),
        "direccion": limpio(direccion),
        "notas": limpio(notas),
    }
    cambiados = [c for c, v in nuevos.items() if (getattr(socio, c) or None) != v]
    for campo, valor in nuevos.items():
        setattr(socio, campo, valor)
    if cambiados:
        anotar(db, num_socio, user, "Datos modificados",
               "Campos modificados: " + ", ".join(cambiados) + ".")
    db.commit()
    return volver(f"/socios/{num_socio}", ok="Datos guardados.")


@app.post("/socios/{num_socio}/baja")
def dar_baja_socio(
    num_socio: int,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    socio = db.get(models.Socio, num_socio)
    if socio:
        socio.estado = "Baja (manual)"
        anotar(db, num_socio, user, "Baja manual",
               f"Dado de baja manualmente por {user.nombre}.")
        db.commit()
    return volver(f"/socios/{num_socio}", ok="Socio dado de baja.")


@app.post("/socios/{num_socio}/reactivar")
def reactivar_socio(
    num_socio: int,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    socio = db.get(models.Socio, num_socio)
    if socio and socio.estado == "Baja (manual)":
        socio.estado = "Inactivo"
        anotar(db, num_socio, user, "Reactivación de socio",
               f"Socio reactivado por {user.nombre}.")
        db.commit()
        comprobar_estados_socios(db)
    return volver(f"/socios/{num_socio}", ok="Socio reactivado.")


@app.post("/socios/{num_socio}/eliminar")
def eliminar_socio(
    num_socio: int,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    socio = db.get(models.Socio, num_socio)
    if not socio:
        return volver("/socios", error="Ese socio no existe.")
    if socio.cuotas:
        return volver(
            f"/socios/{num_socio}",
            error="Tiene recibos emitidos, así que no se puede eliminar. "
                  "Puedes darlo de baja.",
        )
    db.query(models.HistorialSocio).filter(
        models.HistorialSocio.num_socio == num_socio
    ).delete()
    db.delete(socio)
    db.commit()
    return volver("/socios", ok=f"Socio #{num_socio} eliminado.")


# --------------------------------------------------------------------------
# Cuotas y recibos
# --------------------------------------------------------------------------

def form_pago(request, db, user, seleccionado, fecha, forma, importe,
              error=None, status_code=200):
    socios = db.query(models.Socio).order_by(models.Socio.nombre).all()
    return render(
        request, db, user, "cuotas/pago.html", status_code=status_code,
        socios=socios, seleccionado=seleccionado, fecha=fecha, forma=forma,
        importe=importe, formas=FORMAS_PAGO, error=error,
    )


@app.get("/cuotas")
def listado_cuotas(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    cuotas = db.query(models.Cuota).order_by(models.Cuota.fecha_pago.desc()).all()
    return render(request, db, user, "cuotas/listado.html", cuotas=cuotas)


@app.get("/cuotas/pago")
def nuevo_pago_form(
    request: Request,
    socio_id: int = None,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    config = get_or_create_config(db)
    return form_pago(
        request, db, user, socio_id,
        datetime.now().strftime("%Y-%m-%dT%H:%M"), "Efectivo",
        config.importe_cuota_defecto,
    )


@app.post("/cuotas/pago")
def registrar_pago(
    request: Request,
    num_socio: int = Form(...),
    fecha_pago: str = Form(...),
    forma_pago: str = Form(...),
    importe: float = Form(None),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    config = get_or_create_config(db)
    if importe is None:
        importe = config.importe_cuota_defecto

    def fallo(mensaje):
        return form_pago(request, db, user, num_socio, fecha_pago,
                         forma_pago, importe, mensaje, 400)

    socio = db.get(models.Socio, num_socio)
    if not socio:
        return fallo("El socio seleccionado no existe.")
    if socio.estado == "Baja (manual)":
        return fallo("Este socio está en baja manual. Reactívalo antes de "
                     "registrar un pago.")
    if forma_pago not in FORMAS_PAGO:
        return fallo("La forma de pago no es válida.")
    if importe <= 0:
        return fallo("El importe debe ser mayor que cero.")
    try:
        f_pago = datetime.fromisoformat(fecha_pago)
    except ValueError:
        return fallo("La fecha del pago no es válida.")

    id_cuota = generar_id_cuota(db, f_pago)
    db.add(models.Cuota(
        id_cuota=id_cuota, num_socio=num_socio, fecha_pago=f_pago,
        forma_pago=forma_pago, importe=importe,
    ))
    anotar(db, num_socio, user, "Pago de cuota",
           f"Registrado el recibo {id_cuota} ({forma_pago}, {formatos.euros(importe)}).")
    db.commit()
    comprobar_estados_socios(db)
    return volver(f"/cuotas/{id_cuota}", ok="Pago registrado.")


@app.get("/cuotas/{id_cuota}")
def detalle_cuota(
    id_cuota: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    cuota = db.get(models.Cuota, id_cuota)
    if not cuota:
        return volver("/cuotas", error="Ese recibo no existe.")
    return render(request, db, user, "cuotas/detalle.html", cuota=cuota)


@app.get("/cuotas/{id_cuota}/ticket")
def ticket_cuota(
    id_cuota: str,
    request: Request,
    imprimir: str = None,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    """Recibo en formato ticket (impresora térmica de 80 mm)."""
    cuota = db.get(models.Cuota, id_cuota)
    if not cuota:
        return volver("/cuotas", error="Ese recibo no existe.")
    return render(request, db, user, "cuotas/ticket.html",
                  cuota=cuota, imprimir=bool(imprimir))


@app.post("/cuotas/{id_cuota}/anular")
def anular_cuota(
    id_cuota: str,
    motivo: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    cuota = db.get(models.Cuota, id_cuota)
    if not cuota:
        return volver("/cuotas", error="Ese recibo no existe.")
    if cuota.anulada:
        return volver(f"/cuotas/{id_cuota}", error="El recibo ya estaba anulado.")
    if not motivo.strip():
        return volver(f"/cuotas/{id_cuota}", error="Indica el motivo de la anulación.")

    cuota.anulada = 1
    cuota.fecha_anulacion = datetime.now()
    cuota.motivo_anulacion = motivo.strip()
    anotar(db, cuota.num_socio, user, "Recibo anulado",
           f"Anulado el recibo {id_cuota}. Motivo: {motivo.strip()}")
    db.commit()
    comprobar_estados_socios(db)
    return volver(f"/cuotas/{id_cuota}", ok="Recibo anulado.")


# --------------------------------------------------------------------------
# Copias de seguridad automáticas
# --------------------------------------------------------------------------

_ultimo_fallo = {"cuando": None}
REINTENTO_TRAS_FALLO = timedelta(minutes=10)


def programa_desde(config) -> copias.Programa:
    return copias.Programa(
        activo=bool(config.backup_activo),
        frecuencia=config.backup_frecuencia or "diaria",
        cada_dias=config.backup_cada_dias or 1,
        dia_semana=config.backup_dia_semana or 0,
        dia_mes=config.backup_dia_mes or 1,
        hora=config.backup_hora or "03:00",
        desde=config.backup_desde,
        ultimo=config.backup_ultimo,
    )


def ejecutar_copia_si_toca():
    ahora = datetime.now()
    with SessionLocal() as db:
        config = get_or_create_config(db)
        if config.backup_activo and not config.backup_desde and not config.backup_ultimo:
            config.backup_desde = ahora       # sin referencia no habría "próxima" copia
            db.commit()
            return
        if not copias.toca(programa_desde(config), ahora):
            return
        if _ultimo_fallo["cuando"] and ahora - _ultimo_fallo["cuando"] < REINTENTO_TRAS_FALLO:
            return
        try:
            destino = copias.crear_copia(DB_PATH, BACKUPS_DIR, ahora)
            copias.podar(BACKUPS_DIR, config.backup_conservar or 14)
            config.backup_ultimo = ahora
            config.backup_ultimo_estado = f"Correcta: {destino.name}"
            _ultimo_fallo["cuando"] = None
        except Exception as e:
            config.backup_ultimo_estado = f"Error: {e}"
            _ultimo_fallo["cuando"] = ahora
        db.commit()


def bucle_copias(parar: threading.Event):
    """Comprueba cada 30 segundos si toca hacer una copia."""
    while not parar.wait(30):
        try:
            ejecutar_copia_si_toca()
        except Exception:
            pass    # un fallo puntual no debe parar el planificador


# --------------------------------------------------------------------------
# Agenda diaria
# --------------------------------------------------------------------------

MAX_NOTA = 2000


def _fecha_agenda(valor):
    try:
        return date.fromisoformat(valor) if valor else date.today()
    except ValueError:
        return date.today()


@app.get("/agenda")
def agenda(
    request: Request,
    fecha: str = None,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    dia = _fecha_agenda(fecha)
    notas = (
        db.query(models.AgendaNota)
        .filter(models.AgendaNota.fecha == dia)
        .order_by(models.AgendaNota.creada, models.AgendaNota.id)
        .all()
    )
    # Últimos días con anotaciones, para poder volver a ellos
    recientes = (
        db.query(models.AgendaNota.fecha, func.count())
        .group_by(models.AgendaNota.fecha)
        .order_by(models.AgendaNota.fecha.desc())
        .limit(12)
        .all()
    )
    return render(
        request, db, user, "agenda.html", dia=dia, notas=notas,
        anterior=dia - timedelta(days=1), siguiente=dia + timedelta(days=1),
        es_hoy=dia == date.today(), hoy=date.today(),
        recientes=[(f, n) for f, n in recientes], max_nota=MAX_NOTA,
    )


@app.post("/agenda")
def agenda_anotar(
    fecha: str = Form(""),
    texto: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    dia = _fecha_agenda(fecha)
    destino = f"/agenda?fecha={dia.isoformat()}"
    texto = texto.strip()
    if not texto:
        return volver(destino, error="Escribe algo antes de guardar la nota.")
    if len(texto) > MAX_NOTA:
        return volver(destino, error=f"La nota es demasiado larga (máximo {MAX_NOTA} caracteres).")
    db.add(models.AgendaNota(fecha=dia, usuario_id=user.id, texto=texto))
    db.commit()
    return volver(destino, ok="Nota guardada.")


@app.post("/agenda/{nota_id}/eliminar")
def agenda_eliminar(
    nota_id: int,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    nota = db.get(models.AgendaNota, nota_id)
    if not nota:
        return volver("/agenda", error="Esa nota no existe.")
    destino = f"/agenda?fecha={nota.fecha.isoformat()}"
    if nota.usuario_id != user.id and user.rol != "admin":
        return volver(destino, error="Solo puede borrar una nota quien la escribió o un administrador.")
    db.delete(nota)
    db.commit()
    return volver(destino, ok="Nota eliminada.")


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------

EXT_LOGO = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
MAX_LOGO = 2 * 1024 * 1024


def borrar_logos_subidos():
    for antiguo in UPLOAD_DIR.glob("logo_*"):
        antiguo.unlink(missing_ok=True)


def guardar_logo(archivo: UploadFile) -> str:
    ext = Path(archivo.filename).suffix.lower()
    if ext not in EXT_LOGO:
        raise ValueError("El logo debe ser PNG, JPG, WEBP, GIF o SVG.")
    datos = archivo.file.read(MAX_LOGO + 1)
    if len(datos) > MAX_LOGO:
        raise ValueError("El logo no puede pesar más de 2 MB.")
    borrar_logos_subidos()
    nombre = f"logo_{uuid.uuid4().hex[:8]}{ext}"
    (UPLOAD_DIR / nombre).write_bytes(datos)
    return f"/static/uploads/{nombre}"


@app.get("/ajustes")
def vista_ajustes(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    usuarios = db.query(models.Usuario).order_by(models.Usuario.nombre).all()
    config = get_or_create_config(db)
    programa = programa_desde(config)
    return render(
        request, db, user, "ajustes.html", usuarios=usuarios,
        def_primario=COLOR_PRIMARIO, def_cabecera=COLOR_CABECERA,
        frecuencias=copias.FRECUENCIAS, dias_semana=copias.DIAS_SEMANA,
        proxima_copia=copias.proxima(programa, datetime.now()),
        descripcion_copia=copias.describir(programa),
        lista_copias=copias.listar(BACKUPS_DIR, 15),
        carpeta_copias=str(BACKUPS_DIR),
    )


@app.post("/ajustes/guardar")
def guardar_ajustes(
    nombre_asociacion: str = Form(""),
    cif: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    direccion: str = Form(""),
    importe_cuota_defecto: float = Form(...),
    color_primario: str = Form(""),
    color_cabecera: str = Form(""),
    quitar_logo: str = Form(None),
    logo: UploadFile = File(None),
    backup_activo: str = Form(None),
    backup_frecuencia: str = Form("diaria"),
    backup_cada_dias: int = Form(1),
    backup_dia_semana: int = Form(0),
    backup_dia_mes: int = Form(1),
    backup_hora: str = Form("03:00"),
    backup_conservar: int = Form(14),
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    if not nombre_asociacion.strip():
        return volver("/ajustes", error="El nombre de la asociación es obligatorio.")
    if importe_cuota_defecto <= 0:
        return volver("/ajustes", error="El importe de la cuota debe ser mayor que cero.")

    config = get_or_create_config(db)
    config.nombre_asociacion = nombre_asociacion.strip()
    config.cif = limpio(cif)
    config.telefono = limpio(telefono)
    config.email = limpio(email)
    config.direccion = limpio(direccion)
    config.importe_cuota_defecto = importe_cuota_defecto
    config.color_primario = color_valido(color_primario, None)
    config.color_cabecera = color_valido(color_cabecera, None)

    # --- copias automáticas ---
    if backup_frecuencia not in {k for k, _ in copias.FRECUENCIAS}:
        return volver("/ajustes", error="La frecuencia de las copias no es válida.")
    if copias.parsear_hora(backup_hora) is None:
        return volver("/ajustes", error="La hora de la copia no es válida (usa el formato HH:MM).")
    if not (1 <= backup_cada_dias <= 365 and 0 <= backup_dia_semana <= 6
            and 1 <= backup_dia_mes <= 31 and 1 <= backup_conservar <= 365):
        return volver("/ajustes", error="Revisa los valores de las copias automáticas.")
    nuevo_horario = (
        1 if backup_activo else 0, backup_frecuencia, backup_cada_dias,
        backup_dia_semana, backup_dia_mes, copias.parsear_hora(backup_hora).strftime("%H:%M"),
    )
    horario_actual = (
        1 if config.backup_activo else 0, config.backup_frecuencia, config.backup_cada_dias,
        config.backup_dia_semana, config.backup_dia_mes, config.backup_hora,
    )
    if nuevo_horario != horario_actual:
        config.backup_desde = datetime.now()      # el nuevo horario cuenta desde ahora
    (config.backup_activo, config.backup_frecuencia, config.backup_cada_dias,
     config.backup_dia_semana, config.backup_dia_mes, config.backup_hora) = nuevo_horario
    config.backup_conservar = backup_conservar

    if logo is not None and logo.filename:
        try:
            config.logo_url = guardar_logo(logo)
        except ValueError as e:
            db.rollback()
            return volver("/ajustes", error=str(e))
    elif quitar_logo:
        borrar_logos_subidos()
        config.logo_url = None

    db.commit()
    return volver("/ajustes", ok="Ajustes guardados.")


@app.post("/ajustes/backups/ahora")
def copia_ahora(
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    """Guarda una copia en la carpeta de backups sin esperar al horario."""
    try:
        destino = copias.crear_copia(DB_PATH, BACKUPS_DIR)
        copias.podar(BACKUPS_DIR, get_or_create_config(db).backup_conservar or 14)
    except Exception as e:
        return volver("/ajustes#copias", error=f"No se pudo crear la copia: {e}")
    return volver("/ajustes#copias", ok=f"Copia guardada: {destino.name}")


@app.get("/ajustes/backups/{nombre}")
def descargar_backup(nombre: str, user=Depends(solo_admin)):
    if not copias.PATRON.match(nombre) or not (BACKUPS_DIR / nombre).is_file():
        return volver("/ajustes#copias", error="Esa copia no existe.")
    return FileResponse(BACKUPS_DIR / nombre, filename=nombre,
                        media_type="application/octet-stream")


@app.get("/ajustes/copia-seguridad")
def copia_seguridad(user=Depends(solo_admin)):
    nombre = f"asociacion_{datetime.now():%Y%m%d_%H%M}.db"
    destino = Path(tempfile.gettempdir()) / nombre
    origen_con = sqlite3.connect(DB_PATH)
    destino_con = sqlite3.connect(destino)
    with destino_con:
        origen_con.backup(destino_con)
    origen_con.close()
    destino_con.close()
    return FileResponse(
        destino, filename=nombre, media_type="application/octet-stream",
        background=BackgroundTask(destino.unlink, missing_ok=True),
    )


# --------------------------------------------------------------------------
# Usuarios
# --------------------------------------------------------------------------

@app.get("/usuarios")
def listado_usuarios(user=Depends(solo_admin)):
    return RedirectResponse("/ajustes#usuarios", status_code=303)


@app.get("/usuarios/nuevo")
def nuevo_usuario_form(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    return render(request, db, user, "usuarios/nuevo.html", datos={}, error=None)


@app.post("/usuarios/nuevo")
def crear_usuario(
    request: Request,
    username: str = Form(...),
    nombre: str = Form(...),
    password: str = Form(...),
    confirmacion: str = Form(...),
    rol: str = Form("gestor"),
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    username = username.strip().lower()
    datos = {"username": username, "nombre": nombre.strip(), "rol": rol}

    def fallo(mensaje):
        return render(request, db, user, "usuarios/nuevo.html",
                      status_code=400, datos=datos, error=mensaje)

    if not username or not datos["nombre"]:
        return fallo("Usuario y nombre son obligatorios.")
    if rol not in ("admin", "gestor"):
        return fallo("El rol no es válido.")
    if (
        db.query(models.Usuario)
        .filter(func.lower(models.Usuario.username) == username)
        .first()
    ):
        return fallo(f"El usuario «{username}» ya existe.")
    if len(password) < 8:
        return fallo("La contraseña debe tener al menos 8 caracteres.")
    if password != confirmacion:
        return fallo("Las contraseñas no coinciden.")

    db.add(models.Usuario(
        username=username, nombre=datos["nombre"], rol=rol, activo=1,
        password_hash=auth.hash_password(password),
    ))
    db.commit()
    return volver("/ajustes#usuarios", ok=f"Usuario «{username}» creado.")


@app.post("/usuarios/{usuario_id}/estado")
def cambiar_estado_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    user=Depends(solo_admin),
):
    objetivo = db.get(models.Usuario, usuario_id)
    if not objetivo:
        return volver("/ajustes#usuarios", error="Ese usuario no existe.")
    if objetivo.id == user.id:
        return volver("/ajustes#usuarios", error="No puedes desactivarte a ti mismo.")
    objetivo.activo = 0 if objetivo.activo else 1
    db.commit()
    accion = "activado" if objetivo.activo else "desactivado"
    return volver("/ajustes#usuarios", ok=f"Usuario «{objetivo.username}» {accion}.")


def _puede_cambiar_clave(user, objetivo):
    return user.rol == "admin" or user.id == objetivo.id


@app.get("/usuarios/{usuario_id}/password")
def password_form(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    objetivo = db.get(models.Usuario, usuario_id)
    if not objetivo:
        return volver("/", error="Ese usuario no existe.")
    if not _puede_cambiar_clave(user, objetivo):
        raise SinPermiso(user)
    return render(request, db, user, "usuarios/password.html",
                  objetivo=objetivo, error=None)


@app.post("/usuarios/{usuario_id}/password")
def cambiar_password(
    usuario_id: int,
    request: Request,
    actual: str = Form(""),
    password: str = Form(...),
    confirmacion: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(usuario_actual),
):
    objetivo = db.get(models.Usuario, usuario_id)
    if not objetivo:
        return volver("/", error="Ese usuario no existe.")
    if not _puede_cambiar_clave(user, objetivo):
        raise SinPermiso(user)

    def fallo(mensaje):
        return render(request, db, user, "usuarios/password.html",
                      status_code=400, objetivo=objetivo, error=mensaje)

    if user.id == objetivo.id and not auth.verify_password(
        actual, objetivo.password_hash
    ):
        return fallo("La contraseña actual no es correcta.")
    if len(password) < 8:
        return fallo("La contraseña nueva debe tener al menos 8 caracteres.")
    if password == CLAVE_INICIAL:
        return fallo("Elige una contraseña distinta de la inicial.")
    if password != confirmacion:
        return fallo("Las contraseñas no coinciden.")

    objetivo.password_hash = auth.hash_password(password)
    db.commit()
    return volver("/", ok="Contraseña actualizada.")

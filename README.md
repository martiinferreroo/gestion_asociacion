# Plataforma de Gestión de Asociación de Vecinos

Pequeña aplicación para la gestión de los socios y de los pagos de sus cuotas en una asociación de vecinos.

Desarrollada con **Python + FastAPI**. Los datos se guardan en un único archivo **SQLite**, lo que hace que instalar, mover o hacer copias de la aplicación sea muy sencillo.

## Funcionalidades

- **Socios**: listado con búsqueda y ordenación, ficha con datos personales, edición, baja manual y reactivación, e historial de cambios (quién hizo qué y cuándo).
- **Cuotas y pagos**: registro de pagos (efectivo, tarjeta o transferencia) con numeración correlativa de recibos (`ARM-CUO2026-001`).
- **Recibos imprimibles**: incluyen el logo, el nombre, el CIF, la dirección, el teléfono y el correo de la asociación definidos en Ajustes. Se imprimen tal y como se ven en pantalla.
- **Ticket de 80 mm**: el mismo recibo en formato ticket para impresora térmica, con el logo y los datos de la asociación ([ver más](#impresión-del-recibo-y-del-ticket)).
- **Anulación de recibos**: los recibos no se borran, se anulan (con motivo) y conservan su número, para que la numeración siga siendo correlativa.
- **Panel de inicio**: estado de los socios, cobrado en el año, últimos pagos y cumpleaños del mes.
- **Importar socios desde Excel o CSV**, con detección automática de columnas y limpieza de datos ([ver más](#importar-y-exportar-socios)).
- **Exportar socios a Excel**.
- **Agenda diaria**: pantalla para anotar observaciones de cada día, con la fecha y el usuario que las escribió ([ver más](#agenda-diaria)).
- **Copias de seguridad automáticas** programables desde Ajustes: frecuencia, hora y número de copias a conservar ([ver más](#copias-de-seguridad)).
- **Usuarios y roles**: administrador y gestor.
- **Ajustes** (solo administradores): datos de la asociación, logo, colores de la aplicación, importe de la cuota, usuarios y copias de seguridad.
- Funciona **sin conexión a internet**: no depende de CDN ni de librerías externas en el navegador.

### Estados de los socios

El estado se calcula a partir del último pago no anulado:

| Estado | Condición |
|---|---|
| **Al día** | Menos de 365 días desde el último pago |
| **Pendiente** | Entre 365 y 730 días desde el último pago |
| **Baja (automática)** | Más de 730 días desde el último pago |
| **Inactivo** | Socio sin ningún pago registrado |
| **Baja (manual)** | Dado de baja a mano; no cambia por sí solo |

### Roles

| Rol | Puede |
|---|---|
| **Gestor** | Socios (alta, edición, baja), cuotas y recibos |
| **Administrador** | Todo lo anterior, más Ajustes, usuarios, importar/exportar y eliminar socios sin recibos |

## Estructura del repositorio

```text
.
├── README.md
├── Dockerfile                  # imagen de la aplicación
├── docker-compose.yml          # cómo se ejecuta con Docker
├── desplegar.sh                # instala o actualiza con Docker
├── instalar-systemd.sh         # instala o actualiza como servicio (sin Docker)
├── .github/workflows/ci.yml    # pruebas automáticas y publicación de la imagen
├── tests/                      # pruebas automáticas
└── src/
    ├── main.py                 # rutas y lógica de la aplicación
    ├── models.py               # tablas de la base de datos
    ├── database.py             # conexión a SQLite y carpeta de datos
    ├── auth.py                 # contraseñas y sesiones firmadas
    ├── importar.py             # lectura y limpieza de Excel/CSV
    ├── exportar.py             # generación del Excel de socios
    ├── formatos.py             # formato de fechas, importes y tamaños
    ├── copias.py               # programación y creación de copias automáticas
    ├── migraciones.py          # cambios de esquema en bases ya existentes
    ├── requirements.txt
    ├── templates/              # páginas (Jinja2)
    └── static/                 # estilos y JavaScript
```

## Instalación

Hay tres formas, de más a menos recomendable para un servidor:

| Forma | Cuándo usarla |
|---|---|
| [**Docker**](#instalación-con-docker-recomendada) | Servidor con Docker. Lo más sencillo de repetir y de actualizar. |
| [**Servicio systemd**](#instalación-sin-docker-servicio-de-linux) | Servidor Linux sin Docker. |
| [**Desarrollo local**](#desarrollo-local) | Para probar o modificar la aplicación en tu ordenador. |

En las tres, lo que cambia con el uso se guarda fuera del código, en dos carpetas. En Docker y systemd están en la raíz del repositorio:

| Carpeta | Contenido |
|---|---|
| `data/` | `asociacion.db` (base de datos), `.secret_key` (clave que firma las sesiones), `uploads/` (logo) y `copias/` (copias previas a cada importación) |
| `backups/` | Copias automáticas de la base de datos, programadas desde Ajustes |

Están separadas a propósito: `backups/` se puede apuntar a otro disco o a un NAS sin tocar nada más (ver [Copias de seguridad](#copias-de-seguridad)).

### Instalación con Docker (recomendada)

Requiere [Docker](https://docs.docker.com/engine/install/) con el plugin Compose.

```bash
git clone <url-del-repositorio> gestion-asociacion
cd gestion-asociacion
./desplegar.sh
```

El script comprueba que Docker está instalado, prepara `data/` con los permisos correctos, construye la imagen y arranca el contenedor. Se puede ejecutar todas las veces que haga falta. La aplicación queda en segundo plano y, con `restart: unless-stopped`, arranca con el servidor y se reinicia si falla.

Abre la aplicación (por defecto en el puerto 8000) y entra con el usuario `admin` y la contraseña `admin123`. **Al entrar te obliga a cambiarla.**

#### Actualizar

```bash
git pull && ./desplegar.sh
```

#### Operación diaria

```bash
docker compose logs -f asociacion    # ver mensajes y errores
docker compose restart asociacion    # reiniciar
docker compose stop                  # parar
docker compose start                 # arrancar
```

#### Trasladar la instalación a otro servidor

Con la aplicación parada en el origen (`docker compose stop`), copia la carpeta `data/` completa (y, si quieres conservar las copias, `backups/`) al mismo sitio del servidor nuevo y ejecuta allí `./desplegar.sh`.

Si vienes de una instalación antigua **sin carpeta de datos** (la base de datos junto a `main.py`), crea `data/` y copia:

| Origen | Destino |
|---|---|
| `src/asociacion.db` | `data/asociacion.db` |
| `src/.secret_key` | `data/.secret_key` |
| `src/static/uploads/*` | `data/uploads/` |

Al arrancar, la base de datos se actualiza sola (se le añaden las columnas nuevas) y no pierdes datos. **Haz una copia del archivo antes, por si acaso.**

#### Descargar la imagen ya construida (opcional)

El flujo de GitHub Actions (`.github/workflows/ci.yml`) publica la imagen en GitHub Container Registry cada vez que se sube código a `main`. Así el servidor no necesita compilar:

```bash
echo "ASOCIACION_IMAGE=ghcr.io/<usuario>/<repositorio>:latest" > .env
docker compose pull && docker compose up -d
```

Si el repositorio es privado, el servidor debe iniciar sesión antes con un token con permiso `read:packages`:

```bash
docker login ghcr.io -u <usuario>
```

### Detrás de un proxy inverso (Nginx Proxy Manager)

El HTTPS lo gestiona el proxy. En `docker-compose.yml` hay dos opciones para que el proxy llegue a la aplicación; usa **una**:

- **A (recomendada)**: NPM está en Docker en la misma máquina. Conecta ambos contenedores a la misma red (descomenta `networks` en el compose) y en NPM apunta a `asociacion:8000`. El puerto no queda expuesto.
- **B**: NPM está en otra máquina. En NPM apunta a `IP_DEL_SERVIDOR:8000` y **limita ese puerto con el firewall** para que solo lo alcance el proxy.

Además, en NPM, en la pestaña **Advanced** del host, añade:

```nginx
client_max_body_size 3m;
```

El límite por defecto (1 MB) impide subir logos algo mayores.

> En Docker se usa `FORWARDED_ALLOW_IPS="*"`, que hace que la aplicación se fíe de las cabeceras del proxy (así sabe que la petición original era HTTPS y marca la cookie de sesión como segura). Es seguro mientras **solo** el proxy pueda llegar al puerto de la aplicación: de ahí la red compartida o el firewall.

### Instalación sin Docker (servicio de Linux)

Requiere Linux con systemd, Python 3.10 o superior y `python3-venv`. Clona el repositorio en `/opt/asociacion` (el servicio se ejecuta con un usuario sin privilegios, que debe poder leer la carpeta) y ejecuta:

```bash
git clone <url-del-repositorio> /opt/asociacion
cd /opt/asociacion
sudo ./instalar-systemd.sh
```

El script crea el usuario `asociacion`, el entorno de Python, la carpeta `data/` y el servicio, y lo arranca. Se puede repetir después de cada `git pull` para actualizar. Opciones:

```bash
sudo PUERTO=8000 FORWARDED_ALLOW_IPS=IP_DEL_PROXY ./instalar-systemd.sh
```

```bash
journalctl -u asociacion -f           # ver mensajes y errores
sudo systemctl restart asociacion     # reiniciar
```

Con un proxy inverso, pon en `FORWARDED_ALLOW_IPS` la IP del proxy y limita el puerto con el firewall, igual que arriba. En Windows se puede registrar uvicorn como servicio con [NSSM](https://nssm.cc); en cualquier caso, lánzalo sin `--reload` y con un único proceso.

### Desarrollo local

Requiere Python 3.10 o superior.

```bash
cd src
pip install -r requirements.txt
uvicorn main:app --reload
```

Abre <http://127.0.0.1:8000>. Si ya tienes una base de datos, copia tu `asociacion.db` en la carpeta `src` (junto a `main.py`) antes de arrancar.

- Ejecuta siempre desde la carpeta donde está `main.py`. Si lo ejecutas desde la raíz del repositorio, indica a uvicorn el directorio: `uvicorn --app-dir src main:app`.
- `--reload` es solo para desarrollar; no lo uses en producción.
- Usa **un único proceso** (no varios `--workers`): SQLite no está pensado para escrituras concurrentes desde varios procesos, y para una asociación va sobrado. El límite de intentos de acceso también vive en la memoria de un solo proceso.

## Variables de entorno

| Variable | Descripción | Por defecto |
|---|---|---|
| `ASOCIACION_DATA` | Carpeta donde se guardan base de datos, clave, logo y copias previas a importar | La carpeta del código (en Docker, `/data`) |
| `ASOCIACION_BACKUPS` | Carpeta de las copias automáticas | `<ASOCIACION_DATA>/backups` (en Docker, `/backups`) |
| `ASOCIACION_COOKIE_SECURE` | Con `1`, la cookie de sesión solo viaja por HTTPS | Automático según el protocolo de la petición |
| `ASOCIACION_SECRET` | Clave de firma de sesiones (sustituye a `.secret_key`) | Se genera en `.secret_key` |
| `FORWARDED_ALLOW_IPS` | IPs de proxy en las que uvicorn confía | `127.0.0.1` |
| `TZ` | Zona horaria de las fechas y horas de los recibos | `Europe/Madrid` en Docker |

## Impresión del recibo y del ticket

En la página de cada recibo (**Cuotas y pagos →** pulsa un recibo) hay dos botones:

- **Imprimir recibo**: hoja A4, tal y como se ve en pantalla.
- **Imprimir ticket**: formato ticket para impresora térmica de **80 mm**. Se abre en una pestaña nueva y lanza el cuadro de impresión. Incluye el logo, el nombre, el CIF, la dirección, el teléfono y el correo de la asociación (los de **Ajustes**), los datos del recibo y del socio, y el importe. Si el recibo está anulado, lo indica.

Ambos usan los datos y el logo definidos en Ajustes.

### Configurar la impresión del ticket

En el cuadro de impresión del navegador:

1. Elige tu **impresora térmica** (con su controlador instalado) y, como tamaño de papel, el de **80 mm** (suele llamarse *Roll Paper 80 mm* o similar).
2. **Márgenes**: ninguno. **Escala**: 100 %. Desactiva *Encabezados y pies de página*.

Si el ticket sale cortado por los lados o con demasiado margen, ajusta el ancho útil en la primera línea de `src/static/ticket.css`:

```css
:root { --ancho-ticket: 72mm; }
```

72 mm es lo habitual en papel de 80 mm. Para papel de 58 mm, prueba con `48mm`.

## Agenda diaria

La pestaña **Agenda** es un pequeño cuaderno para anotar cuatro cosas de cada día: una incidencia, un recado, algo que recordar.

- Se abre en el día de hoy. Con **Anterior**, **Siguiente**, **Hoy** o el selector de fecha se navega a cualquier otro día, y a la derecha aparece la lista de los últimos días con anotaciones.
- Cada nota guarda el **día** al que se refiere, **quién** la escribió y **a qué hora**. Si se escribe una nota en un día distinto al de su fecha, se indica la fecha completa.
- Todos los usuarios pueden escribir. Solo puede **eliminar** una nota quien la escribió o un administrador.
- Máximo 2000 caracteres por nota; se respetan los saltos de línea.

## Importar y exportar socios

Ambas funciones están en **Socios** y son solo para administradores.

### Exportar

**Exportar a Excel** descarga un `.xlsx` con nombre, apellidos, DNI, dirección, fecha de nacimiento, teléfono y correo de todos los socios, ordenados por apellidos.

### Importar

**Importar desde Excel** acepta `.xlsx` y `.csv` (hasta 5 MB y 5000 filas). Los `.xls` antiguos hay que guardarlos antes como `.xlsx`.

1. **Sube el archivo.**
2. **Indica qué hay en cada columna.** El programa lo deduce por los encabezados y por el contenido, y tú corriges lo que haga falta. Aquí también marcas si **la primera fila son los nombres de las columnas** (se ignora al importar) y eliges la hoja si el Excel tiene varias. Puedes usar el mismo destino en varias columnas (dos teléfonos, o calle y número).
3. **Elige si sobrescribir** y pulsa **Comprobar sin guardar** (simulación con recuento y avisos) o **Importar**.

Un socio **ya existe** si coincide su Nº de socio o, si el archivo no lo trae, su DNI real.

| Opción "Sobrescribir" | Qué ocurre con un socio que ya existe |
|---|---|
| **Activada** | Se guardan los datos del archivo y los datos anteriores pasan a *Observaciones* (con la fecha de la importación). Solo se sobrescribe lo que el archivo trae. |
| **Desactivada** | Prevalecen los datos ya registrados; del archivo solo se rellenan los campos vacíos. |

**DNI**: los socios nuevos sin DNI se guardan con el provisional `12345678Z` (se muestra la etiqueta *Provisional* en su ficha). Un socio que ya tiene un DNI real no lo pierde por esto.

**Limpieza automática**:

- Nombres en mayúsculas o minúsculas, espacios de más, y nombre y apellidos juntos en una columna (`Pérez Ruiz, Ana` o `Ana Pérez Ruiz`).
- Fechas en casi cualquier formato, incluidas las de Excel.
- DNI/NIE con guiones o espacios; si falta la letra, se calcula.
- Teléfonos guardados como número, y varios teléfonos o correos en una misma celda.
- Nº de socio repetido en el archivo: se asigna uno nuevo, siempre por encima del mayor existente.
- DNI real duplicado con otro socio: se guarda con el provisional y el original queda en Observaciones.
- **Nada se pierde**: lo que no encaja (teléfono no válido, fecha imposible, segundo correo…) queda anotado en Observaciones, y el informe indica cada aviso con su número de fila de Excel.

Antes de cada importación se hace una **copia automática** de la base de datos en `copias/` (se conservan las 10 últimas).

> Los nombres completos en una sola columna se dividen con una regla aproximada, y en los que no traen coma es ambigua (`Ana María Pérez`). El informe indica cuántos se dividieron automáticamente para que se revisen.

## Copias de seguridad

### Copias automáticas

En **Ajustes → Copias de seguridad automáticas** (solo administradores) se programa una copia periódica de la base de datos (socios, pagos, agenda, usuarios y ajustes):

| Opción | Valores |
|---|---|
| **Frecuencia** | Todos los días, cada *N* días, una vez a la semana (a elegir el día) o una vez al mes (a elegir el día del mes) |
| **Hora** | La que quieras, por ejemplo `03:00` para hacerla de madrugada |
| **Copias que se conservan** | Número de copias; al superarlo se borran solas las más antiguas |

- Se guardan en la carpeta `backups/` como `asociacion_AAAA-MM-DD_HHMMSS.db`. En Ajustes se ven las copias existentes, se pueden descargar y se puede hacer una **copia ahora** sin esperar al horario.
- La pantalla muestra cuándo será la próxima copia y el resultado de la última (con el error, si lo hubo).
- Si el servidor estaba apagado a la hora prevista, la copia se hace al volver a encenderse (una sola, no una por cada hueco).
- Al cambiar el horario, la cuenta empieza desde ese momento.
- Las copias se hacen con el mecanismo de copia en caliente de SQLite, así que son consistentes aunque alguien esté usando la aplicación. Se usa la hora del servidor (`TZ`).
- Solo se copia la base de datos. El logo (`data/uploads/`) y la clave de sesión (`data/.secret_key`) están en `data/`.
- Los archivos de `backups/` que no sigan ese nombre no se tocan nunca.

### Guardar las copias en otro disco o NAS

En Docker, `backups/` es un volumen aparte. Cambia la ruta de la izquierda en `docker-compose.yml` (por ejemplo, un NAS ya montado en el servidor) y ejecuta `./desplegar.sh`:

```yaml
volumes:
  - ./data:/data
  - /mnt/nas/asociacion:/backups
```

Sin Docker, define `ASOCIACION_BACKUPS` con la ruta (en el servicio de systemd, edita la línea `Environment=ASOCIACION_BACKUPS=...`). La carpeta debe ser escribible por el usuario del servicio.

> Una copia en el mismo disco no protege de un fallo del disco. Lleva de vez en cuando `backups/` fuera del servidor.

### Restaurar una copia

Con la aplicación parada, sustituye la base de datos por la copia elegida:

```bash
docker compose stop
cp data/asociacion.db data/asociacion_antes_de_restaurar.db      # por si acaso
sudo cp backups/asociacion_2026-09-29_030000.db data/asociacion.db
sudo chown 1000:1000 data/asociacion.db                          # con systemd: el usuario "asociacion"
docker compose start
```

### Otras copias

- **Ajustes → Copias guardadas → Descargar la base de datos actual** descarga una copia en el momento. Guárdala fuera del servidor.
- Para copiar todo (datos y logo) con la aplicación parada:

    ```bash
    docker compose stop && tar czf copia_$(date +%F).tar.gz data && docker compose start
    ```

- Antes de cada importación se guarda una copia automática en `data/copias/` (se conservan las 10 últimas).
- La primera vez que se arranca una versión con cambios de esquema, se guarda una copia junto a la base de datos (`asociacion_antes_de_migrar_*.db`).

## Pruebas

La lógica de importación, la exportación, las migraciones de la base de datos, la programación de las copias automáticas y las plantillas (recibo, ticket, agenda y ajustes) tienen pruebas automáticas, que no necesitan nada más que las dependencias de la aplicación:

```bash
pip install -r src/requirements.txt
python -m unittest discover -s tests -t . -v
```

GitHub Actions las ejecuta en cada `push` y en cada *pull request*.

## Seguridad y protección de datos

La aplicación gestiona datos personales de socios (RGPD).

- **No subas nunca al repositorio** la base de datos, `.secret_key` ni las copias. El `.gitignore` incluido ya lo evita. Si la base de datos llegó a subirse alguna vez, seguirá en el historial de Git aunque la borres; habría que limpiarlo.
- Todas las rutas exigen iniciar sesión. Las sesiones van firmadas, caducan a las 8 horas y la cookie es `HttpOnly` y `SameSite`.
- Tras 5 intentos fallidos con un usuario (o 20 desde una misma IP) el acceso se bloquea 5 minutos.
- La documentación automática de la API (`/docs`) está desactivada, y las páginas con datos personales no se guardan en la caché del navegador.
- `.secret_key` firma las sesiones. No lo compartas. Si lo borras, todos tendrán que volver a iniciar sesión.
- Cambia la contraseña inicial `admin123` (la aplicación te obliga al primer acceso).
- No expongas la aplicación a internet sin HTTPS.
- Los usuarios se desactivan, no se borran, para conservar el historial de quién hizo cada cambio y cada nota de la agenda.
- Un socio con recibos emitidos no se puede eliminar; se da de baja.

## Notas

- El DNI no es único en la base de datos, porque varios socios pueden tener el provisional. La unicidad de los DNI reales se comprueba en el código. La migración necesaria se aplica sola al arrancar (con copia previa).
- Las sesiones anteriores a una actualización de seguridad dejan de valer: hay que volver a entrar una vez.

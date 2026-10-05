import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# Ruta absoluta: la base de datos siempre está junto al código,
# sin importar desde qué carpeta se lance el servidor.
BASE_DIR = Path(__file__).resolve().parent
# Todo lo que cambia con el uso (base de datos, clave, logo, copias) vive en
# DATA_DIR. Por defecto es la carpeta del código; en Docker se usa /data.
DATA_DIR = Path(os.environ.get("ASOCIACION_DATA", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "asociacion.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def _activar_claves_foraneas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

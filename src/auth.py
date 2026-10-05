import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from database import DATA_DIR
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# --- Sesiones firmadas ---------------------------------------------------
# La cookie contiene "id_usuario:caducidad:firma". La clave se guarda en
# .secret_key (o en la variable ASOCIACION_SECRET), así que las sesiones
# sobreviven a los reinicios y no se pueden falsificar sin conocerla.

SESSION_SECONDS = 8 * 3600
_KEY_FILE = DATA_DIR / ".secret_key"


def _cargar_clave() -> bytes:
    desde_entorno = os.environ.get("ASOCIACION_SECRET")
    if desde_entorno:
        return desde_entorno.encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    clave = secrets.token_hex(32).encode()
    _KEY_FILE.write_bytes(clave)
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    return clave


_SECRET = _cargar_clave()


def _firmar(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def crear_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + SESSION_SECONDS}"
    return base64.urlsafe_b64encode(
        f"{payload}:{_firmar(payload)}".encode()
    ).decode()


def leer_token(token: str):
    """Devuelve el id de usuario si el token es válido y no ha caducado."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, caduca, firma = raw.split(":")
        if not hmac.compare_digest(firma, _firmar(f"{user_id}:{caduca}")):
            return None
        if int(caduca) < time.time():
            return None
        return int(user_id)
    except Exception:
        return None

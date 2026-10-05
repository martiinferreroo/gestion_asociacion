#!/usr/bin/env bash
# Instala o actualiza la aplicación como servicio de systemd (Linux, sin Docker).
# Ejecútalo con sudo desde la raíz del repositorio. Se puede repetir las veces
# que haga falta (por ejemplo, después de un git pull).
#
# Opciones (variables de entorno):  PUERTO=8000  FORWARDED_ALLOW_IPS=127.0.0.1
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "Ejecútalo con sudo:  sudo ./instalar-systemd.sh"; exit 1; }
command -v python3 >/dev/null || { echo "Falta python3."; exit 1; }
command -v systemctl >/dev/null || { echo "Este script necesita systemd."; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
USUARIO="asociacion"
PUERTO="${PUERTO:-8000}"
IP_PROXY="${FORWARDED_ALLOW_IPS:-127.0.0.1}"

case "$REPO" in
    /home/*|/root/*)
        echo "Aviso: el servicio se ejecuta con el usuario '$USUARIO' y puede no tener"
        echo "acceso a $REPO. Si falla, clona el repositorio en /opt/asociacion."
        ;;
esac

id "$USUARIO" >/dev/null 2>&1 || useradd --system --home-dir "$REPO" --shell /usr/sbin/nologin "$USUARIO"

echo "Preparando el entorno de Python (si falla: apt install python3-venv)..."
python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install --quiet --upgrade pip
"$REPO/.venv/bin/pip" install --quiet -r "$REPO/src/requirements.txt"

mkdir -p "$REPO/data"
chown -R "$USUARIO" "$REPO/data"

cat > /etc/systemd/system/asociacion.service <<UNIT
[Unit]
Description=Gestión de la asociación de vecinos
After=network.target

[Service]
User=$USUARIO
WorkingDirectory=$REPO/src
Environment=ASOCIACION_DATA=$REPO/data
Environment=FORWARDED_ALLOW_IPS=$IP_PROXY
ExecStart=$REPO/.venv/bin/uvicorn main:app --host 0.0.0.0 --port $PUERTO --proxy-headers
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable asociacion >/dev/null
systemctl restart asociacion
sleep 2
systemctl --no-pager --lines=5 status asociacion || true
echo
echo "Listo. Registros:  journalctl -u asociacion -f"

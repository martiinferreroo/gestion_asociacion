#!/usr/bin/env bash
# Instala o actualiza la aplicación. Se puede ejecutar todas las veces que haga falta.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Falta Docker: https://docs.docker.com/engine/install/"; exit 1; }

mkdir -p data
# El contenedor se ejecuta con el usuario 1000: debe poder escribir en data/
if [ "$(stat -c %u data)" != "1000" ]; then
    chown -R 1000:1000 data 2>/dev/null || sudo chown -R 1000:1000 data
fi

docker compose up -d --build
docker compose ps
echo
echo "Listo. Registros:  docker compose logs -f asociacion"

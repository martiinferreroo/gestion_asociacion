#!/usr/bin/env bash
# Instala o actualiza la aplicación. Se puede ejecutar todas las veces que haga falta.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Falta Docker: https://docs.docker.com/engine/install/"; exit 1; }

mkdir -p data backups
# El contenedor se ejecuta con el usuario 1000: debe poder escribir en estas carpetas
for carpeta in data backups; do
    if [ "$(stat -c %u "$carpeta")" != "1000" ]; then
        chown -R 1000:1000 "$carpeta" 2>/dev/null || sudo chown -R 1000:1000 "$carpeta"
    fi
done

docker compose up -d --build
docker compose ps
echo
echo "Listo. Registros:  docker compose logs -f asociacion"

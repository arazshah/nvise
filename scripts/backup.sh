#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"
mkdir -p "${DEST}"

POSTGRES_DB="${POSTGRES_DB:-nvise}"
POSTGRES_USER="${POSTGRES_USER:-nvise}"

echo "Creating PostgreSQL backup..."
docker compose -f "${COMPOSE_FILE}" exec -T db \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc > "${DEST}/database.dump"

echo "Creating private media backup..."
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps \
  -v "${PWD}/${DEST#./}:/backup" \
  web sh -c 'tar -C /app/private_media -czf /backup/private_media.tar.gz .'

sha256sum "${DEST}/database.dump" "${DEST}/private_media.tar.gz" > "${DEST}/SHA256SUMS"
echo "Backup completed: ${DEST}"

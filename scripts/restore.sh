#!/usr/bin/env bash
set -euo pipefail

if [[ "${NVISE_RESTORE_CONFIRM:-}" != "YES" ]]; then
  echo "Refusing restore. Set NVISE_RESTORE_CONFIRM=YES after verifying the target environment."
  exit 2
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: NVISE_RESTORE_CONFIRM=YES bash scripts/restore.sh <backup-directory>"
  exit 2
fi

BACKUP_DIR="$1"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
POSTGRES_DB="${POSTGRES_DB:-nvise}"
POSTGRES_USER="${POSTGRES_USER:-nvise}"

sha256sum -c "${BACKUP_DIR}/SHA256SUMS"

echo "Restoring PostgreSQL..."
docker compose -f "${COMPOSE_FILE}" exec -T db \
  pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists < "${BACKUP_DIR}/database.dump"

echo "Restoring private media..."
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps \
  -v "${PWD}/${BACKUP_DIR#./}:/backup:ro" \
  web sh -c 'rm -rf /app/private_media/* && tar -C /app/private_media -xzf /backup/private_media.tar.gz'

echo "Restore completed. Run migrations and readiness checks before enabling traffic."

#!/usr/bin/env bash
set -Eeuo pipefail

app_dir="${1:-/opt/citepilot}"
backup_dir="${CITEPILOT_BACKUP_DIR:-$app_dir/backups}"
retention_days="${CITEPILOT_BACKUP_RETENTION_DAYS:-14}"

if [[ ! "$retention_days" =~ ^[0-9]+$ ]]; then
  echo "backup: retention days must be a positive integer" >&2
  exit 2
fi

cd "$app_dir"
umask 077
mkdir -p "$backup_dir"

compose=(docker compose --env-file .env.production -f compose.production.yml)
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$backup_dir/postgres-$timestamp.sql.gz"
temporary="$destination.partial"
trap 'rm -f "$temporary"' EXIT

echo "backup: writing $destination"
"${compose[@]}" exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --clean --if-exists --no-owner --no-privileges --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
  | gzip -9 > "$temporary"
mv "$temporary" "$destination"
trap - EXIT

find "$backup_dir" -type f -name 'postgres-*.sql.gz' -mtime "+$retention_days" -delete
echo "backup: complete"

#!/usr/bin/env bash
set -Eeuo pipefail

release_sha="${1:-}"
app_dir="${2:-/opt/citepilot}"

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "deploy: expected a full 40-character Git commit SHA" >&2
  exit 2
fi
if [[ ! "$app_dir" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  echo "deploy: unsafe application directory" >&2
  exit 2
fi
if [[ ! -d "$app_dir/.git" ]]; then
  echo "deploy: $app_dir is not a Git checkout" >&2
  exit 2
fi
if [[ ! -f "$app_dir/.env.production" ]]; then
  echo "deploy: create $app_dir/.env.production before deploying" >&2
  exit 2
fi

cd "$app_dir"

# Refuse concurrent deploys and refuse to overwrite hand-edited server files.
exec 9>"$app_dir/.deploy.lock"
if ! flock -n 9; then
  echo "deploy: another deployment is already running" >&2
  exit 3
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "deploy: server checkout has tracked modifications; refusing to overwrite them" >&2
  exit 3
fi

previous_sha="$(git rev-parse HEAD)"
export CITEPILOT_IMAGE_TAG="$release_sha"
compose=(docker compose --env-file .env.production -f compose.production.yml)

rollback() {
  local exit_code=$?
  trap - ERR
  echo "deploy: release $release_sha failed; attempting application rollback" >&2
  "${compose[@]}" logs --tail=120 backend worker web >&2 || true

  if [[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]] && git cat-file -e "$previous_sha^{commit}"; then
    git checkout --detach "$previous_sha"
    export CITEPILOT_IMAGE_TAG="$previous_sha"
    "${compose[@]}" build backend web || true
    "${compose[@]}" up -d --remove-orphans || true
  fi
  exit "$exit_code"
}
trap rollback ERR

echo "deploy: fetching $release_sha"
git fetch --quiet origin "$release_sha"
git cat-file -e "$release_sha^{commit}"
git checkout --detach "$release_sha"

"${compose[@]}" config --quiet

# Bring durable stores up first, create a pre-migration backup, then build the
# exact commit and migrate before replacing application containers.
"${compose[@]}" up -d postgres neo4j redis
"$app_dir/infra/deploy/backup-postgres.sh" "$app_dir"
"${compose[@]}" build --pull backend web
"${compose[@]}" run --rm --no-deps backend alembic upgrade head
"${compose[@]}" up -d --remove-orphans

published="$("${compose[@]}" port web 8080 | tail -1)"
if [[ -z "$published" ]]; then
  echo "deploy: web port was not published" >&2
  false
fi
health_url="http://${published}/api/health"

echo "deploy: waiting for $health_url"
healthy=false
for _ in $(seq 1 30); do
  if response="$(curl --fail --silent --show-error --max-time 8 "$health_url")" \
    && grep -q '"status":"ok"' <<<"$response"; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  echo "deploy: health gate failed" >&2
  false
fi

printf '%s\n' "$release_sha" > "$app_dir/.deployed-sha"
trap - ERR
echo "deploy: $release_sha is healthy"

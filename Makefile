up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-shell:
	docker compose exec backend bash

web-shell:
	docker compose exec web sh

migrate:
	docker compose exec backend alembic upgrade head

test-backend:
	docker compose exec backend pytest

resync-graph:
	docker compose exec backend python -m app.graph.resync

prod-config:
	docker compose --env-file .env.production -f compose.production.yml config --quiet

prod-up:
	docker compose --env-file .env.production -f compose.production.yml up -d --build

prod-down:
	docker compose --env-file .env.production -f compose.production.yml down

prod-logs:
	docker compose --env-file .env.production -f compose.production.yml logs -f --tail=200

prod-backup:
	./infra/deploy/backup-postgres.sh "$(CURDIR)"

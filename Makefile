.PHONY: up down logs backend-shell web-shell migrate test-backend resync-graph \
	edge-network prod-config prod-up prod-down prod-logs prod-backup

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

edge-network:
	@docker network inspect portfolio-edge >/dev/null 2>&1 || docker network create portfolio-edge

prod-up: edge-network
	docker compose --env-file .env.production -f compose.production.yml up -d --build

prod-down:
	docker compose --env-file .env.production -f compose.production.yml down

prod-logs:
	docker compose --env-file .env.production -f compose.production.yml logs -f --tail=200

prod-backup:
	./infra/deploy/backup-postgres.sh "$(CURDIR)"

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
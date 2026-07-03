FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["arq", "app.workers.arq_app.WorkerSettings"]
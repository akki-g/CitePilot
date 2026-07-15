# Python worker image; backend and arq run here.
FROM python:3.12-slim

# Unbuffered logs show up immediately in Docker; no pyc files keeps the image cleaner.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Backend package root.
WORKDIR /app/backend

# curl/ca-certificates are needed to install Tectonic.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Tectonic. The official drop installer 404s on arm64 (it requests a
# *-gnu build that has no release asset), so fetch the static musl binary for
# the current architecture directly from GitHub releases.
RUN arch="$(uname -m)" \
 && curl --proto '=https' --tlsv1.2 -fsSL \
    "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-${arch}-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin tectonic

# Pre-warm the bundle with the same preamble as the bootstrap main.tex.
RUN printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp \
 && rm -f /tmp/warmup.*

# Copy backend source and install editable package/dependencies.
COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

# arq imports this settings object to discover job functions.
CMD ["arq", "app.workers.arq_app.WorkerSettings"]
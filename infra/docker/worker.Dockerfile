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

# Install Tectonic (official installer drops the binary in cwd).
RUN cd /tmp \
 && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
 && mv /tmp/tectonic /usr/local/bin/tectonic

# Pre-warm the bundle with the same preamble as the bootstrap main.tex.
RUN printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp \
 && rm -f /tmp/warmup.*

# Copy backend source and install editable package/dependencies.
COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

# arq imports this settings object to discover job functions.
CMD ["arq", "app.workers.arq_app.WorkerSettings"]
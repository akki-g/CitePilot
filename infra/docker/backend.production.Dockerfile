FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XDG_CACHE_HOME=/var/cache/tectonic

WORKDIR /app/backend

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN arch="$(uname -m)" \
 && curl --proto '=https' --tlsv1.2 -fsSL \
    "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-${arch}-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin tectonic

# Warm the LaTeX bundle in a shared cache so the non-root runtime never needs
# to download packages while compiling a user or demo project.
RUN mkdir -p "$XDG_CACHE_HOME" \
 && printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp \
 && rm -f /tmp/warmup.*

COPY --from=uv /uv /usr/local/bin/uv
COPY backend/ ./
RUN uv sync --locked --no-dev --no-editable \
 && useradd --system --uid 10001 --create-home --home-dir /home/citepilot citepilot \
 && chown -R citepilot:citepilot /app/backend "$XDG_CACHE_HOME"

ENV PATH="/app/backend/.venv/bin:$PATH"

USER citepilot

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

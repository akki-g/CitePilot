FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN arch="$(uname -m)" \
 && curl --proto '=https' --tlsv1.2 -fsSL \
    "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-${arch}-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin tectonic

# Cache the Tectonic bundle in the image so anonymous previews never fetch
# packages from the network at request time.
RUN printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp \
 && rm -f /tmp/warmup.*

COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

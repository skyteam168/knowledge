# syntax=docker/dockerfile:1.7
# Targets: `worker` (dramatiq / outbox dispatcher / scheduler) and `api` (default, last stage).
# Both share one image layout; only the default command differs.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder

# Optional heavy PDF backend (layout models): docker build --build-arg INSTALL_DOCLING=true
ARG INSTALL_DOCLING=false

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DOCLING" = "true" ]; then EXTRAS="--extra ocr --extra docling"; else EXTRAS="--extra ocr"; fi \
    && uv sync --frozen --no-dev --no-install-project $EXTRAS


FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

# libgl1 / libglib2.0-0: OpenCV (pulled in by rapidocr). tini: PID 1 signal forwarding + reaping.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

USER app

ENTRYPOINT ["tini", "--", "/app/docker-entrypoint.sh"]


FROM runtime AS worker
# LibreOffice Writer (headless) converts legacy .doc to .docx before parsing; only the worker parses.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*
USER app
CMD ["dramatiq", "app.workers.main", "--processes", "2", "--threads", "4"]


FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# WEB_CONCURRENCY = uvicorn worker processes (each has its own DB pool: see DATABASE_POOL_SIZE).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]

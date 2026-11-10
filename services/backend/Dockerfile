# Mixt AI backend image (API, worker, migrate and restore-check commands).
# Build from services/backend: docker build -t mixt-backend .
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY mixt ./mixt
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 mixt
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
USER mixt
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"]
# Migrations run as a separate step before rollout: `python -m mixt.cli migrate` (see infra/staging).
# Client addresses come from X-Forwarded-For only via MIXT_TRUSTED_PROXIES (mixt.api.net), so
# uvicorn's own proxy-header handling is switched off.
CMD ["uvicorn", "mixt.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header"]

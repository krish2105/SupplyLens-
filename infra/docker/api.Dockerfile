# API and worker image (same code, different command). Python 3.12, locked dependencies via uv.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 postgresql-client && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY services ./services
COPY ml ./ml
COPY optimisation ./optimisation
RUN uv sync --frozen --no-dev
COPY scripts ./scripts
COPY fixtures ./fixtures
COPY knowledge/synthetic_contracts ./knowledge/synthetic_contracts
COPY data/synthetic ./data/synthetic
RUN useradd -r -u 10001 supplylens && mkdir -p /app/storage && chown -R supplylens /app/storage
USER supplylens
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "supplylens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

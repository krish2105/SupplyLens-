# API and worker image (same code, different command). Python 3.12, locked dependencies via uv.
#
# PyTorch is installed in its own early layer so dependency changes never re-download it. By default it comes
# from PyTorch's CPU index (no CUDA libraries). Where that host is unreachable, build with
#   --build-arg TORCH_INDEX=https://pypi.org/simple     (larger image: PyPI's wheel bundles CUDA runtime deps)
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE} AS base
ARG APT_PACKAGES="ca-certificates libgomp1 postgresql-client"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY infra/docker/ca/ /usr/local/share/ca-certificates/extra/
# APT_PACKAGES="" skips apt (for networks that block Debian mirrors; use a base image that already has libgomp1)
RUN update-ca-certificates \
    && if [ -n "$APT_PACKAGES" ]; then apt-get update && apt-get install -y --no-install-recommends $APT_PACKAGES \
       && update-ca-certificates && rm -rf /var/lib/apt/lists/*; fi
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt UV_NATIVE_TLS=1
RUN pip install --no-cache-dir uv==0.11.18
WORKDIR /app

FROM base AS torch
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.14.1
RUN uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install "torch==${TORCH_VERSION}" --index-url "${TORCH_INDEX}" \
       --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match

FROM torch AS final
COPY pyproject.toml uv.lock ./
COPY services ./services
COPY ml ./ml
COPY optimisation ./optimisation
# torch is provided by the layer above (the lock pins the CPU build for Linux; the layer matches its version)
RUN uv sync --frozen --no-dev --inexact --no-install-package torch
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

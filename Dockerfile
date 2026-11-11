# API image: engine + FastAPI, with the processed data bundle baked in.
FROM python:3.13-slim AS api

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" NUMBA_CACHE_DIR=/var/cache/numba \
    VLAB_DATA_DIR=/app/data VLAB_CACHE_DIR=/var/cache/vlab
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY engine ./engine
COPY api ./api
RUN uv sync --frozen --no-dev

COPY data/raw/gtfs_tuc_pamplona.zip ./data/raw/gtfs_tuc_pamplona.zip
COPY data/processed ./data/processed
# Compile the numba kernels and build the walking tables at image build time, so the
# container is ready a few seconds after it starts instead of after a minute.
RUN mkdir -p /var/cache/numba /var/cache/vlab /app/data/cache \
 && python -c "from vlab.model import Model; from vlab_api.service import Service; Service(Model.load()).warm_up()"

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=120s --retries=40 \
  CMD python -c "import json,urllib.request,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health'))['status']=='ok' else 1)"
CMD ["uvicorn", "vlab_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

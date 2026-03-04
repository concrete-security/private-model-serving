# ghcr.io/astral-sh/uv:debian-slim
FROM ghcr.io/astral-sh/uv@sha256:2301babdaa11591889ea3933304912ba0814503fd89242819fdd8e7610d80c88

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml /app/
COPY uv.lock /app/
RUN uv sync --locked --no-cache

COPY model_service.py /app/

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD uv run python -c \
    'import requests; res = requests.get("http://localhost:8001/health"); exit(res.status_code != 200)'

CMD ["uv", "run", "fastapi", "run", "model_service.py", "--host", "0.0.0.0", "--port", "8001"]

# ghcr.io/astral-sh/uv:debian-slim
FROM ghcr.io/astral-sh/uv@sha256:2301babdaa11591889ea3933304912ba0814503fd89242819fdd8e7610d80c88

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml /app/
COPY uv.lock /app/
RUN uv sync --locked --no-cache

COPY utils.py /app/
COPY app.py /app/

EXPOSE 8001

CMD ["uv", "run", "fastapi", "run", "app.py", "--host", "0.0.0.0", "--port", "8001"]

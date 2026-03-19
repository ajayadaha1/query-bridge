FROM python:3.12-slim AS base

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[server,postgresql,sqlite,snowflake,export]"

# Copy demo database
COPY demo/ demo/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "querybridge.server.api:app", "--host", "0.0.0.0", "--port", "8000"]

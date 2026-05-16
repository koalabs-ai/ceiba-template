# Dockerfile — generic container for any provider (Fly, Render, GCP Run, fly, Railway, your own VPS).

FROM python:3.11-slim

WORKDIR /app

# System deps kept minimal — sqlite ships with python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-apply schema. The data/ dir should be mounted as a volume for persistence.
RUN mkdir -p data \
    && python -c "import sqlite3, os; \
                  db='data/db.sqlite'; \
                  c=sqlite3.connect(db); \
                  c.executescript(open('sql/001_init.sql').read()); \
                  c.commit()" \
    && echo "schema applied at build time (volume should preserve runtime writes)"

EXPOSE 8080

# Healthcheck hits the manifest's /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]

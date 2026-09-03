FROM python:3.12-slim

# libmagic1 is required at runtime by python-magic (MIME sniffing for uploads).
# libpq5 is required at runtime by psycopg2-binary's Postgres client.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
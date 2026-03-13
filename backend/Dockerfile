FROM python:3.12-slim

# Install docker CLI (needed for `docker compose` commands)
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io docker-compose-v2 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

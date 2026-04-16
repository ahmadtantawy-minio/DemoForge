FROM python:3.12-slim
# register-webhook.sh downloads mc with curl; slim image has neither by default
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY integration_log.py server.py .
RUN mkdir -p /app/scenarios
EXPOSE 8090 8091
CMD ["python", "server.py"]
